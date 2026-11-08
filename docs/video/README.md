# 视频：第一周怎么准备 + 用 GoLand 一步一步 debug

[`week1-goland-debug.mp4`](week1-goland-debug.mp4)：中文配音，7 分 10 秒，1080p，内含一条可开关的中文字幕轨；字幕也单独放在 [`week1-goland-debug.srt`](week1-goland-debug.srt)。

GitHub 网页预览不了这么大的视频，点进文件后用 **Download raw file** 下载，或者克隆仓库后在本地播放。

## 内容

| 时间段 | 内容 |
| --- | --- |
| 开头 | 第一周的三个目标、要装的工具、拉源码和图谱、两条自检命令、每天 2 小时的节奏 |
| 第 1～7 天 | 每天学什么、读哪些代码、当天的产出，对应 [学习路线](../learning-path.md) 的阶段 0～2 |
| 重点：GoLand | 准备项目 → 运行配置 → 打断点 → 启动调试 → 8 个单步按键 → 实战跟一个 Pod 事件（`HandleDeltas → processDeltas → clientState.Add → handler.OnAdd → 你的 AddFunc`）→ 条件断点 → 第二周用同样方法调 kube-scheduler |
| 结尾 | 第一周验收标准 |

几点说明：

- 练习程序的 `k8s.io/client-go`、`k8s.io/api`、`k8s.io/apimachinery` 用 **v0.31.14**，单步进入源码后行号才和图谱一致。
- 视频里的快捷键是 GoLand 在 Windows / Linux 下的默认键位，macOS 以 Settings → Keymap 为准。
- IDE 画面（调用栈、变量面板）是按 client-go 源码画的示意图，真机上调用栈里会多几层 runtime 帧。

## 自己改旁白、重新生成

画面、旁白文字和生成脚本都在 [`voiceover/`](voiceover/)。旁白在 `narration.json`，每一屏一段；改完运行脚本即可。某一屏的旁白比画面长时，脚本会自动延长这一屏，声画始终同步。

需要 Python 3.8+ 和 ffmpeg（Windows：`winget install ffmpeg`；macOS：`brew install ffmpeg`；Ubuntu：`sudo apt install ffmpeg`）。在 `docs/video/voiceover` 目录执行：

```bash
# 方式一：和仓库里视频同一个女声，完全离线
pip install onnxruntime numpy
curl -L https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-melo-tts-zh_en.tar.bz2 | tar xj
python make_voiced.py --engine melo

# 方式二：微软在线语音，男声 Yunxi（默认），需联网，免费、不需要账号
pip install edge-tts
python make_voiced.py                                   # 女声加 --voice zh-CN-XiaoxiaoNeural，调语速加 --rate +15%

# 其他：macOS 系统语音 --engine say；Windows 系统语音 --engine sapi；只测流程 --engine test
```

生成的视频和字幕在 `voiceover` 目录里（`-o 文件名` 可改）。语音按段缓存在 `_build/voice/`，重新运行只合成改过的段落。

离线引擎用的是开源模型 [MeloTTS](https://github.com/myshell-ai/MeloTTS)（MIT 许可，模型由 [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) 转换），文本前端在 `melo_tts.py`：用模型自带词典做分词、中文数字读法、「一」「不」变调、驼峰标识符拆词。某个词读得不对，在 `melo_tts.py` 里加一行：英文加到 `SAY`，中文多音字加到 `PHRASES`。
