#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bge_onnx_engine.py — BGE 语义层 onnxruntime 后端
================================================
治本修复（R-fix-2）：原 BGE 走 sentence_transformers/torch，但本机 torch 原生
崩溃（access violation，0xC0000005），且 transformers 的 Rust `tokenizers` 原生库
同样在本机崩溃（两者均崩，onnxruntime 正常）——属机器级原生库硬不兼容。
改用 onnxruntime 直接加载 BGE 的 ONNX 权重 + 纯 Python 自实现 BERT(中文) 分词器，
零 torch / 零 tokenizers 依赖。

复刻 sentence_transformers 编码语义（保证与 bge_fullbody_embeddings.npy 同语义空间）：
  - 分词：纯 Python BERT WordPiece（do_lower_case=False, tokenize_chinese_chars=True,
          strip_accents=None —— 对齐 BAAI tokenizer_config.json）
  - 前向：onnxruntime 推理 last_hidden_state
  - 池化：CLS token（1_Pooling: pooling_mode_cls_token=true）
  - 归一：L2 Normalize（2_Normalize 层）
与 build_indexes.encode_bge 的 SentenceTransformer.encode 数学等价（同权重/同池化/同归一）。
"""
import os
import json
import unicodedata
from pathlib import Path
import numpy as np

BAAI_SNAPSHOT = os.path.expanduser(
    r'~/.cache/huggingface/hub/models--BAAI--bge-small-zh-v1.5/snapshots/7999e1d3359715c523056ef9478215996d62a620')
ONNX_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bge_onnx', 'onnx', 'model.onnx')
VOCAB_PATH = os.path.join(BAAI_SNAPSHOT, 'vocab.txt')
MAX_LENGTH = 512
CLS_ID, SEP_ID, UNK_ID, PAD_ID = 101, 102, 100, 0

# R206-01: vocab 持久化缓存（JSON 而非 pickle——缓存文件即使被篡改也不会执行任意代码）
_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_cache')
VOCAB_CACHE = os.path.join(_CACHE_DIR, 'bge_vocab.json')
VOCAB = None


# ============ 纯 Python BERT(中文) 分词器 ============
def _is_whitespace(ch):
    if ch in (' ', '\t', '\n', '\r'):
        return True
    return unicodedata.category(ch) == 'Zs'


def _is_control(ch):
    if ch in ('\t', '\n', '\r'):
        return False
    return unicodedata.category(ch).startswith('C')


def _is_punctuation(ch):
    cp = ord(ch)
    if (33 <= cp <= 47) or (58 <= cp <= 64) or (91 <= cp <= 96) or (123 <= cp <= 126):
        return True
    return unicodedata.category(ch).startswith('P')


def _is_chinese_char(cp):
    return ((0x4E00 <= cp <= 0x9FFF) or (0x3400 <= cp <= 0x4DBF) or
            (0x20000 <= cp <= 0x2A6DF) or (0x2A700 <= cp <= 0x2B95F) or
            (0x2B740 <= cp <= 0x2B81F) or (0x2B820 <= cp <= 0x2CEAF) or
            (0xF900 <= cp <= 0xFAFF) or (0x2F800 <= cp <= 0x2FA1F))


def _clean_text(text):
    out = []
    for ch in text:
        cp = ord(ch)
        if cp == 0 or cp == 0xFFFD or _is_control(ch):
            continue
        out.append(' ' if _is_whitespace(ch) else ch)
    return ''.join(out)


def _tokenize_chinese_chars(text):
    out = []
    for ch in text:
        if _is_chinese_char(ord(ch)):
            out.append(' ')
            out.append(ch)
            out.append(' ')
        else:
            out.append(ch)
    return ''.join(out)


def _run_split_on_punc(text):
    chars = list(text)
    out, cur, start_new = [], [], True
    for c in chars:
        if _is_punctuation(c):
            if cur:
                out.append(''.join(cur))
                cur = []
            out.append(c)
            start_new = True
        else:
            if start_new:
                cur = []
                start_new = False
            cur.append(c)
    if cur:
        out.append(''.join(cur))
    return out


def _word_piece(token, vocab, unk_id=UNK_ID, max_chars=100):
    """返回 token 字符串列表（非 id），id 转换在 _encode_one 统一处理。"""
    if len(token) > max_chars:
        return ['[UNK]']
    sub_tokens, start = [], 0
    while start < len(token):
        end = len(token)
        cur = None
        while start < end:
            sub = token[start:end]
            if start > 0:
                sub = '##' + sub
            if sub in vocab:
                cur = sub
                break
            end -= 1
        if cur is None:
            return ['[UNK]']
        sub_tokens.append(cur)
        start = end
    return sub_tokens


def _basic_tokenize(text, do_lower_case=False):
    text = _clean_text(text)
    text = _tokenize_chinese_chars(text)
    out = []
    for tok in text.split():  # whitespace_tokenize
        for piece in _run_split_on_punc(tok):
            if do_lower_case:
                piece = piece.lower()
            if piece in ('[UNK]', '[CLS]', '[SEP]', '[PAD]', '[MASK]'):
                out.append(piece)
            else:
                out.extend(_word_piece(piece, VOCAB))
    return out


def _load_vocab():
    """R206-01: vocab 持久化缓存。21万行 vocab.txt 每次构造 BgeOnnxEncoder 都全量
    逐行解析建 dict（≈100-300ms 冷启动税）；缓存后仅 vocab.txt 变更（mtime 晚于缓存）
    时重建一次，其余冷启动直接 json.load。"""
    global VOCAB
    if isinstance(VOCAB, dict) and VOCAB:
        return
    os.makedirs(_CACHE_DIR, exist_ok=True)
    try:
        if os.path.isfile(VOCAB_CACHE) and \
                os.path.getmtime(VOCAB_CACHE) >= os.path.getmtime(VOCAB_PATH):
            VOCAB = json.loads(Path(VOCAB_CACHE).read_text(encoding='utf-8'))
            if isinstance(VOCAB, dict) and len(VOCAB) > 10000:
                return
    except Exception:
        # 缓存缺失/损坏/过期 → 回退下方全量解析（性能项：若反复出现需排查
        # _cache/bge_vocab.json 可写性；R207 P2-1 留痕）
        pass
    with Path(VOCAB_PATH).open(encoding='utf-8') as _f:
        VOCAB = {t.rstrip('\n'): i for i, t in enumerate(_f)}
    tmp = Path(VOCAB_CACHE + '.tmp')
    tmp.write_text(json.dumps(VOCAB, ensure_ascii=False), encoding='utf-8')
    os.replace(tmp, VOCAB_CACHE)  # 原子替换（lessons-p0 #7 防线③）


class BgeOnnxEncoder:
    """对齐 sentence_transformers.SentenceTransformer.encode 接口的 ONNX 后端。"""

    def __init__(self):
        if not os.path.isfile(ONNX_PATH):
            raise FileNotFoundError(f'BGE ONNX 权重缺失: {ONNX_PATH}')
        if not os.path.isfile(VOCAB_PATH):
            raise FileNotFoundError(f'BGE vocab 缺失: {VOCAB_PATH}')
        _load_vocab()
        import onnxruntime as ort
        so = ort.SessionOptions()
        so.intra_op_num_threads = max(1, os.cpu_count() or 1)
        # R206-01 附带（报告 P2-7）：显式约束 inter_op 线程防多实例并发时核争用
        so.inter_op_num_threads = max(1, (os.cpu_count() or 1) // 2)
        self._sess = ort.InferenceSession(ONNX_PATH, sess_options=so,
                                          providers=['CPUExecutionProvider'])
        self._dim = 512
        self._do_lower = False

    def _encode_one(self, text):
        toks = ['[CLS]'] + _basic_tokenize(text, self._do_lower) + ['[SEP]']
        ids = [VOCAB.get(t, UNK_ID) for t in toks][:MAX_LENGTH]
        return ids

    def encode(self, texts, batch_size=32, show_progress_bar=False, normalize_embeddings=True):
        """对齐 SentenceTransformer.encode 签名。返回 [n, 512] float32 numpy。"""
        single = isinstance(texts, str)
        if single:
            texts = [texts]
        all_emb = []
        for i in range(0, len(texts), batch_size):
            chunk = texts[i:i + batch_size]
            ids_list = [self._encode_one(t) for t in chunk]
            max_len = min(MAX_LENGTH, max(len(x) for x in ids_list))
            ids, tts, attn = [], [], []
            for x in ids_list:
                pad = max_len - len(x)
                ids.append(x + [PAD_ID] * pad)
                tts.append([0] * max_len)
                attn.append([1] * len(x) + [0] * pad)
            out = self._sess.run(
                ['last_hidden_state'],
                {'input_ids': np.array(ids, np.int64),
                 'attention_mask': np.array(attn, np.int64),
                 'token_type_ids': np.array(tts, np.int64)})[0]
            cls = out[:, 0, :].astype(np.float32)
            if normalize_embeddings:
                norms = np.linalg.norm(cls, axis=1, keepdims=True)
                norms[norms == 0] = 1.0
                cls = cls / norms
            all_emb.append(cls)
        embs = np.vstack(all_emb) if all_emb else np.zeros((0, self._dim), np.float32)
        return embs[0] if single else embs


if __name__ == '__main__':
    enc = BgeOnnxEncoder()
    samples = ['如何安装技能', 'Python 读取 Excel 文件', '生成一张风景图片']
    v = enc.encode(samples)
    print('shape:', v.shape, '| norm:', np.linalg.norm(v, axis=1))
    cs = v / np.linalg.norm(v, axis=1, keepdims=True)
    print('cos(安装技能, Python读Excel):', round(float(cs[0] @ cs[1]), 3))
    print('cos(安装技能, 生成图片):', round(float(cs[0] @ cs[2]), 3))
