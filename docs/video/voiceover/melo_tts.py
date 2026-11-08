"""Offline Chinese + English TTS with the MeloTTS ONNX model packaged by sherpa-onnx.

Model: https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-melo-tts-zh_en.tar.bz2
(MIT, MyShell.ai). Needs only numpy + onnxruntime; the text frontend below replaces jieba with
longest-match segmentation over the model's own lexicon.
"""
import os, re, wave
import numpy as np

CN_DIGITS = "零一二三四五六七八九"
PUNCT = {"，": ",", "、": ",", "：": ",", "；": ",", "。": ".", "！": "!", "？": "?", ",": ",", ".": ".",
         "!": "!", "?": "?", "…": "…", "（": ",", "）": ",", "(": ",", ")": ","}

# How to say identifiers that are not in the lexicon (written as words the lexicon knows,
# or as "@phones|tones" for an explicit pronunciation).
SAY = {
    "kubelet": "cube let", "kubectl": "cube control", "kube": "cube", "kubeconfig": "cube config",
    "apiserver": "A P I server", "apimachinery": "A P I machinery", "goroutine": "go routine",
    "nginx": "engine x", "npx": "N P X", "ua": "U A", "wsl": "W S L", "cpu": "C P U", "api": "A P I",
    "fifo": "@f ay f ow|7 9 7 8", "workqueue": "work queue", "err": "error", "ctrl": "control",
    "goland": "go land", "impl": "@ih m p ah l|7 9 7 8 7", "func": "@f ah ng k|7 9 7 7",
    "deltas": "@d eh l t ah z|7 9 7 7 8 7", "lister": "@l ih s t er|7 9 7 7 8", "cmd": "command",
    "srt": "S R T", "json": "jason", "dlv": "D L V", "init": "@ih n ih t|8 7 9 7",
    "sync": "sink", "obj": "object",
    "kubernetes": "@k uw b er n eh t iy z|7 8 7 8 7 9 7 8 7", "reflector": "@r ih f l eh k t er|7 8 7 7 9 7 7 8",
    "iteration": "@ih t er ey sh ah n|8 7 8 9 7 8 7", "config": "@k aa n f ih g|7 9 7 7 8 7", "docs": "@d aa k s|7 9 7 7",
}

# Chinese phrases whose lexicon reading is wrong in this context (pinyin initial/final + tone per phone).
PHRASES = {
    "命令行": "m ing l ing h ang|4 4 4 4 2 2", "一行一行": "y i h ang y i h ang|4 4 2 2 4 4 2 2",
    "第一行": "d i y i h ang|4 4 1 1 2 2", "那一行": "n a y i h ang|4 4 4 4 2 2", "得懂": "d e d ong|5 5 3 3",
}


def cn_int(n):
    """Integer -> Chinese reading (enough for 0..99999)."""
    if n == 0:
        return "零"
    units = [(10000, "万"), (1000, "千"), (100, "百"), (10, "十")]
    out, zero = "", False
    for u, name in units:
        d = n // u
        if d:
            if zero:
                out += "零"; zero = False
            out += ("" if (u == 10 and d == 1 and not out) else CN_DIGITS[d]) + name
            n %= u
        elif out:
            zero = True
    if n:
        out += ("零" if zero else "") + CN_DIGITS[n]
    return out


def normalize(text):
    text = re.sub(r"(\d+)((?:\.\d+)+)", lambda m: " " + " ".join(cn_int(int(m.group(1))) + "".join(
        "点" + "".join(CN_DIGITS[int(c)] for c in p) for p in m.group(2).split(".")[1:])) + " ", text)
    text = re.sub(r"(?<![A-Za-z])\.(?=[A-Za-z])", " 点 ", text)          # .ua
    text = re.sub(r"(?<=[A-Za-z])\.(?=[A-Za-z])", " 点 ", text)          # clientState.Add
    text = text.replace("+", " 加 ").replace("/", " 斜杠 ").replace("-", " ").replace("_", " ")
    text = re.sub(r"\d+", lambda m: cn_int(int(m.group())), text)
    return text


class Melo:
    def __init__(self, model_dir, length_scale=1.0):
        import onnxruntime as ort
        self.tok = {}
        for line in open(os.path.join(model_dir, "tokens.txt"), encoding="utf-8"):
            p = line.rstrip("\n").rsplit(" ", 1)
            if len(p) == 2:
                self.tok[p[0]] = int(p[1])
        self.lex = {}
        for line in open(os.path.join(model_dir, "lexicon.txt"), encoding="utf-8"):
            f = line.split()
            n = (len(f) - 1) // 2
            self.lex[f[0]] = (f[1:1 + n], [int(t) for t in f[1 + n:]])
        for w, v in PHRASES.items():
            p, t = v.split("|")
            self.lex[w] = (p.split(), [int(x) for x in t.split()])
        self.maxlen = 8
        opts = ort.SessionOptions(); opts.intra_op_num_threads = os.cpu_count() or 4
        name = "model.onnx"
        self.sess = ort.InferenceSession(os.path.join(model_dir, name), opts, providers=["CPUExecutionProvider"])
        self.length_scale = length_scale
        self.unknown = set()

    def english(self, word):
        """One English token -> (phones, tones). Splits camelCase and letters/digits."""
        lw = word.lower()
        if lw in SAY:
            s = SAY[lw]
            if s.startswith("@"):
                ph, tn = s[1:].split("|")
                return ph.split(), [int(t) for t in tn.split()]
            assert s.lower() != lw, lw
            return self.words(s.split())
        if lw in self.lex:
            return self.lex[lw]
        parts = re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+", word)
        if len(parts) > 1:
            return self.words(parts)
        if len(lw) <= 3:                      # short acronyms: spell out
            return self.words(list(lw))
        self.unknown.add(word)
        return self.words(list(lw))

    def words(self, ws):
        ph, tn = [], []
        for w in ws:
            p, t = self.english(w) if re.match(r"[A-Za-z]", w) else self.chinese(w)
            ph += p; tn += t
        return ph, tn

    def chinese(self, s):
        segs, i = [], 0
        while i < len(s):
            for L in range(min(self.maxlen, len(s) - i), 0, -1):
                w = s[i:i + L]
                if w in self.lex:
                    segs.append([w, list(self.lex[w][0]), list(self.lex[w][1])]); i += L
                    break
            else:
                self.unknown.add(s[i]); i += 1
        # tone sandhi for a standalone 一 / 不 (words in the lexicon already carry it)
        for k, (w, ph, tn) in enumerate(segs):
            if w not in ("一", "不"):
                continue
            prev = segs[k - 1][0][-1] if k else ""
            nxt = segs[k + 1] if k + 1 < len(segs) else None
            nxt2 = segs[k + 2][0][0] if k + 2 < len(segs) else ""
            if nxt is None:
                continue
            nt = nxt[2][0]
            if w == "一":
                if (prev and prev in CN_DIGITS + "第统十百千万点") or (nxt[0][0] == "点" and nxt2 and nxt2 in CN_DIGITS) or nxt[0][0] in CN_DIGITS:
                    continue
                t = 2 if nt == 4 else 4
            else:
                t = 2 if nt == 4 else 4
            segs[k][2] = [t] * len(tn)
        ph, tn = [], []
        for _, p, t in segs:
            ph += p; tn += t
        return ph, tn

    def frontend(self, text):
        text = normalize(text)
        ph, tn = [], []
        for m in re.finditer(r"[A-Za-z][A-Za-z0-9]*|[一-鿿]+|[，、：；。！？,.!?…（）()]", text):
            t = m.group()
            if t in PUNCT:
                ph.append(PUNCT[t]); tn.append(0)
            elif re.match(r"[A-Za-z]", t):
                p, q = self.english(t); ph += p; tn += q
            else:
                p, q = self.chinese(t); ph += p; tn += q
        return ph, tn

    def ids(self, text):
        ph, tn = self.frontend(text)
        ph = ["_"] + ph + ["_"]; tn = [0] + tn + [0]
        x = [self.tok.get(p, self.tok["UNK"]) for p in ph]
        bx, bt = [0], [0]
        for a, b in zip(x, tn):
            bx += [a, 0]; bt += [b, 0]
        return bx, bt

    def synth(self, text):
        x, t = self.ids(text)
        y = self.sess.run(None, {
            "x": np.array([x], dtype=np.int64), "x_lengths": np.array([len(x)], dtype=np.int64),
            "tones": np.array([t], dtype=np.int64), "sid": np.array([1], dtype=np.int64),
            "noise_scale": np.array([0.667], dtype=np.float32), "length_scale": np.array([self.length_scale], dtype=np.float32),
            "noise_scale_w": np.array([0.8], dtype=np.float32)})[0]
        return y.reshape(-1)

    def to_wav(self, text, out, sr=44100):
        """Synthesize sentence by sentence (better prosody), with short pauses between sentences."""
        pieces = [s for s in re.findall(r"[^。！？；]+[。！？；]?", text) if s.strip()]
        gap = {"。": 0.32, "！": 0.32, "？": 0.32, "；": 0.22}
        audio = []
        for i, s in enumerate(pieces):
            y = self.synth(s)
            audio.append(y)
            if i < len(pieces) - 1:
                audio.append(np.zeros(int(sr * gap.get(s.strip()[-1], 0.15)), dtype=np.float32))
        y = np.concatenate(audio)
        peak = np.max(np.abs(y)) or 1.0
        y = np.clip(y / peak * 0.89, -1, 1)
        with wave.open(out, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
            w.writeframes((y * 32767).astype(np.int16).tobytes())
