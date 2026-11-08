#!/usr/bin/env python3
"""给「k8s 第一周准备与 GoLand 单步调试」视频配音，生成带中文配音和字幕轨的 MP4。

用法（在本文件所在目录执行）：
  pip install edge-tts                 # 只有默认引擎需要；需要联网
  python make_voiced.py                # 默认：微软 edge-tts 中文男声 zh-CN-YunxiNeural
  python make_voiced.py --voice zh-CN-XiaoxiaoNeural --rate +5%   # 换女声、调语速
  python make_voiced.py --engine say   # macOS 离线，系统自带 Tingting 中文语音
  python make_voiced.py --engine sapi  # Windows 离线，系统自带中文语音（如 Huihui）
  python make_voiced.py --engine melo  # 完全离线的开源模型 MeloTTS（女声），需 pip install onnxruntime numpy，
                                       # 并把 vits-melo-tts-zh_en 模型目录放在本目录（见 使用说明.txt）
  python make_voiced.py --engine test  # 不发声，用提示音代替，只检查流程

需要：Python 3.8+、ffmpeg 与 ffprobe 在 PATH 中。
画面和旁白一一对应：某一屏的旁白比画面长，就把这一屏自动延长，声画始终同步。
旁白文字在 narration.json 里，改完重新运行即可；已生成的语音会缓存，只重做改动过的部分。
"""
import argparse, asyncio, hashlib, json, math, os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FPS, X, FADE = 30, 0.5, 0.35      # 帧率、同一场景内两屏的交叉淡化、场景首尾淡入淡出
LEAD, TAIL = 0.35, 0.6             # 每屏开口前留白、说完后留白
ENC = ["-c:v", "libx264", "-crf", "18", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-r", str(FPS)]
SAY_FIX = [("Ctrl", "Control"), (".ua", "点 U A"), ("k8s", "K8S"), ("/", " 斜杠 ")]

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def run(cmd, what):
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if r.returncode != 0:
        sys.exit(f"{what} 失败：\n{r.stderr.decode('utf-8', 'replace')[-1500:]}")
    return r.stdout.decode("utf-8", "replace")


def duration(path):
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path], "ffprobe").strip())


def spoken(text):
    for a, b in SAY_FIX:
        text = text.replace(a, b)
    return text


_MELO = None


def tts(text, out, a):
    """把一段旁白合成为音频文件 out。"""
    global _MELO
    if a.engine == "melo":
        if _MELO is None:
            sys.path.insert(0, HERE)
            from melo_tts import Melo
            if not os.path.isfile(os.path.join(a.model_dir, "model.onnx")):
                sys.exit(f"找不到模型 {a.model_dir}，下载方法见 使用说明.txt")
            _MELO = Melo(a.model_dir, length_scale=a.length_scale)
        _MELO.to_wav(text, out)   # melo_tts 自己做中文数字、英文标识符的读法处理
        return
    if a.engine == "edge":
        import edge_tts
        for attempt in range(3):
            try:
                asyncio.run(edge_tts.Communicate(spoken(text), a.voice, rate=a.rate).save(out))
                return
            except Exception as e:
                if attempt == 2:
                    sys.exit(f"edge-tts 合成失败（检查网络，或改用 --engine say / sapi）：{e}")
    with tempfile.TemporaryDirectory() as td:
        txt = os.path.join(td, "t.txt")
        with open(txt, "w", encoding="utf-8") as f:
            f.write(spoken(text))
        if a.engine == "say":
            run(["say", "-v", a.voice if a.voice_set else "Tingting", "-o", out, "-f", txt], "say")
        elif a.engine == "sapi":
            ps1 = os.path.join(td, "s.ps1")
            with open(ps1, "w", encoding="utf-8-sig") as f:
                f.write("param($in,$out)\nAdd-Type -AssemblyName System.Speech\n"
                        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer\n"
                        "$v = $s.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo } | Where-Object { $_.Culture.Name -eq 'zh-CN' } | Select-Object -First 1\n"
                        "if ($v) { $s.SelectVoice($v.Name) } else { Write-Error '没有找到中文语音，请在 设置→时间和语言→语音 里添加中文' ; exit 1 }\n"
                        "$s.Rate = 1\n$s.SetOutputToWaveFile($out)\n"
                        "$s.Speak([IO.File]::ReadAllText($in, [Text.Encoding]::UTF8))\n$s.Dispose()\n")
            run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps1, txt, out], "Windows 语音合成")
        else:  # test：按每秒 5 个字估算时长，用提示音代替
            d = max(1.0, len(text) / 5.0)
            run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=330:duration={d:.2f}",
                 "-af", "volume=0.15", out], "生成提示音")


def srt_time(t):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"


def chunks(text):
    """按句号、分号、问号切成字幕行；过长的再按逗号切。"""
    out = []
    for s in re.findall(r"[^。；？！]+[。；？！]?", text):
        s = s.strip()
        if len(s) > 30:
            parts = re.findall(r"[^，：]+[，：]?", s)
            cur = ""
            for p in parts:
                if cur and len(cur) + len(p) > 30:
                    out.append(cur); cur = ""
                cur += p
            if cur:
                out.append(cur)
        elif s:
            out.append(s)
    return [c.rstrip("，。；：") for c in out]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--engine", choices=["edge", "melo", "say", "sapi", "test"], default="edge")
    ap.add_argument("--model-dir", default=os.path.join(HERE, "vits-melo-tts-zh_en"), help="melo 模型目录")
    ap.add_argument("--length-scale", type=float, default=1.0, help="melo 语速，越小越快，如 0.9")
    ap.add_argument("--voice", default=None, help="edge 默认 zh-CN-YunxiNeural；say 默认 Tingting")
    ap.add_argument("--rate", default="+8%", help="edge 语速，如 +0%%、+15%%")
    ap.add_argument("-o", "--output", default=os.path.join(HERE, "k8s-第一周准备与GoLand单步调试-配音版.mp4"))
    a = ap.parse_args()
    a.output = os.path.abspath(a.output)
    os.makedirs(os.path.dirname(a.output), exist_ok=True)
    a.voice_set = a.voice is not None
    a.voice = a.voice or "zh-CN-YunxiNeural"

    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            sys.exit(f"找不到 {tool}。Windows：winget install ffmpeg；macOS：brew install ffmpeg；Ubuntu：apt install ffmpeg")
    if a.engine == "edge":
        try:
            import edge_tts  # noqa: F401
        except ImportError:
            sys.exit("缺少 edge-tts：先运行 pip install edge-tts（或改用 --engine say / sapi 离线合成）")

    scenes = json.load(open(os.path.join(HERE, "narration.json"), encoding="utf-8"))
    build = os.path.join(HERE, "_build"); cache = os.path.join(build, "voice"); os.makedirs(cache, exist_ok=True)
    ext = {"edge": ".mp3", "melo": ".wav", "say": ".aiff", "sapi": ".wav", "test": ".wav"}[a.engine]

    # 1. 合成每一屏的旁白，算出每屏实际时长
    total_states = sum(len(s) for _, s in scenes)
    plan, k = [], 0
    for name, states in scenes:
        rows = []
        for frame, base, text in states:
            k += 1
            key = hashlib.sha1(f"{a.engine}|{a.voice}|{a.rate}|{a.length_scale}|{spoken(text)}".encode()).hexdigest()[:16]
            audio = os.path.join(cache, key + ext)
            if not os.path.exists(audio):
                print(f"[{k}/{total_states}] 合成语音 {frame}")
                tmp = audio[:-len(ext)] + ".part" + ext
                tts(text, tmp, a)
                os.replace(tmp, audio)
            d = duration(audio)
            length = math.ceil(max(base, LEAD + d + TAIL) * FPS) / FPS
            rows.append(dict(frame=os.path.join(HERE, "frames", frame), text=text, audio=audio, dur=d, len=length))
        plan.append((name, rows))

    # 2. 每个场景编码一段无声视频（同场景内各屏交叉淡化，场景首尾淡入淡出）
    clips = []
    for si, (name, rows) in enumerate(plan, 1):
        out = os.path.join(build, f"{name}.mp4"); clips.append(out)
        n, total = len(rows), sum(r["len"] for r in rows)
        cmd = ["ffmpeg", "-y", "-v", "error"]
        for r in rows:
            cmd += ["-framerate", str(FPS), "-i", r["frame"]]
        lens = [r["len"] + (X if i < n - 1 else 0) for i, r in enumerate(rows)]
        parts = [f"[{i}:v]format=yuv420p,loop=-1:1,trim=duration={lens[i]:.4f},setpts=PTS-STARTPTS[s{i}]" for i in range(n)]
        last, off = "s0", 0.0
        for i in range(1, n):
            off += rows[i - 1]["len"]
            parts.append(f"[{last}][s{i}]xfade=transition=fade:duration={X}:offset={off:.4f}[x{i}]"); last = f"x{i}"
        parts.append(f"[{last}]fade=t=in:st=0:d={FADE},fade=t=out:st={total - FADE:.4f}:d={FADE},trim=duration={total:.4f}[v]")
        tmp = out[:-4] + ".part.mp4"
        print(f"[{si}/{len(plan)}] 编码画面 {name}  {total:.1f}s")
        run(cmd + ["-filter_complex", ";".join(parts), "-map", "[v]"] + ENC + [tmp], f"编码 {name}")
        os.replace(tmp, out)

    lst = os.path.join(build, "list.txt")
    with open(lst, "w", encoding="utf-8") as f:
        f.writelines(f"file '{os.path.basename(c)}'\n" for c in clips)
    video = os.path.join(build, "video.mp4")
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", video], "拼接画面")

    # 3. 拼一条完整音轨：每屏 = 留白 + 旁白 + 补齐到该屏时长
    rows = [r for _, rs in plan for r in rs]
    cmd = ["ffmpeg", "-y", "-v", "error"]
    for r in rows:
        cmd += ["-i", r["audio"]]
    parts = [f"[{i}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=mono,adelay={int(LEAD * 1000)},"
             f"apad,atrim=0:{r['len']:.4f},asetpts=PTS-STARTPTS[a{i}]" for i, r in enumerate(rows)]
    parts.append("".join(f"[a{i}]" for i in range(len(rows))) + f"concat=n={len(rows)}:v=0:a=1[a]")
    audio = os.path.join(build, "voice.m4a")
    print("合成音轨")
    run(cmd + ["-filter_complex", ";".join(parts), "-map", "[a]", "-c:a", "aac", "-b:a", "160k", audio], "合成音轨")

    # 4. 字幕：按句切分，时间按字数比例分配到该屏的语音时长里
    srt, idx, t = [], 1, 0.0
    for r in rows:
        cs = chunks(r["text"]); total_chars = sum(len(c) for c in cs) or 1; s = t + LEAD
        for c in cs:
            e = s + r["dur"] * len(c) / total_chars
            srt.append(f"{idx}\n{srt_time(s)} --> {srt_time(e)}\n{c}\n"); idx += 1; s = e
        t += r["len"]
    srt_path = os.path.splitext(a.output)[0] + ".srt"
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(srt))

    # 5. 合成最终文件：画面直接复制，加音轨和可开关的字幕轨
    tmp = os.path.splitext(a.output)[0] + ".part.mp4"
    run(["ffmpeg", "-y", "-v", "error", "-i", video, "-i", audio, "-i", srt_path,
         "-map", "0:v", "-map", "1:a", "-map", "2:s", "-c:v", "copy", "-c:a", "copy", "-c:s", "mov_text",
         "-metadata:s:a:0", "language=chi", "-metadata:s:s:0", "language=chi", "-movflags", "+faststart", tmp], "合成最终文件")
    os.replace(tmp, a.output)
    print(f"\n完成：{a.output}\n时长 {duration(a.output):.1f} 秒；字幕另存为 {srt_path}")


if __name__ == "__main__":
    main()
