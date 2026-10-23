# 3D Demo 链接极速分发指南 · 工程师即用型物料包

> **核心策略**：工程师群体最反感冗长的营销说辞和冷冰冰的代码仓库，最喜欢**“有图有真相、免安装直接能上手玩、解决实际脏活累活”**。  
> **核心破圈武器**：
> - 🌐 **3D 在线治具体验站**：`https://mo9652962-ai.github.io/wave-fixture-ai/`
> - 🌐 **EDA 网页云端工作台**：`https://mo9652962-ai.github.io/circuit-agent/`

---

## 场景一：微信群 / QQ 硬件技术群 / PCBA 工厂群（闪电直发版）

> **适用场景**：日常交流、有人吐槽波峰焊治具难画/画错撞件时，直接复制甩出。

### 模板 1（痛点共鸣型 · 极高回复率）
```text
大家画波峰焊治具还在用 CAD 一笔笔偏移和掏避位吗？
分享一个开源的波峰焊治具生成引擎，传 KiCad/Gerber 自动把沉板清角、迎锡面60°倒角、防浮渣槽全算好，还带 3D 元件碰撞干涉检测和 71 项 DRC 门禁。
不用本地配 Python，做了个纯前端 3D 体验站，点开就能直接转着看：
👉 https://mo9652962-ai.github.io/wave-fixture-ai/
（私有板子也能本地跑 uvx wave-fixture-ai 100% 离线出 DXF 和机床 G 代码）
```

### 模板 2（技术求评型 · 低调显硬核）
```text
做了一个面向波峰焊治具的开源 CAM 自动化工具，把 APTPCB/Macaos 的工艺规范固化成了 71 条 DRC 门禁（防炸锡/防浮力翘曲/钛合金薄壁刀片）。
做了一个纯前端的免装 3D 在线演示，内置了 STM32 四层板和空调板两个真实案例，支持 3D 元件碰撞高亮排查：
👉 https://mo9652962-ai.github.io/wave-fixture-ai/
同行兄弟们帮忙看看这个避位倒角和排渣槽的规则还有啥能改进的没？
```

---

## 场景二：立创开源硬件平台 / 电子发烧友 / 21ic 论坛

### 帖子标题
`【开源工装】告别手工描图！波峰焊治具 1秒全自动生成，支持 3D 避位旋转与元件干涉检测（附免安装 3D 在线体验）`

### 正文内容
```markdown
各位硬件工程师、PCBA 制造工友们好：

以往每逢贴片插件混装的板子，做波峰焊治具（过锡炉治具）总是非常枯燥：
要手工做外轮廓 Offset、手工处理内凹锐角铣刀留下的圆弧（还要手动加清角）、手工测量底面贴片器件的高度避位，万一算错高度，压盖扣上去就直接压碎元件。

最近我们将这套 CAM 制造逻辑彻底开源封装成了工具 —— **wave-fixture-ai**：
1. **自动沉板与清角**：外形外扩 0.2mm，自动生成 R1.85 狗骨头清角耳孔（防板框卡角）；
2. **波峰流体导流与防渣**：迎锡侧自动生成 60° 导流斜面，前缘生成 8mm 宽 Ersa 标准防浮渣破浪槽；
3. **3D 实体孪生与元件碰撞高亮**：直接读取 KiCad 元件高度，3D 旋转实时高亮撞件区域；
4. **全套工业文件直出**：71 项 DRC 门禁过审后，直接生成分层清晰的 AutoCAD DXF、水密 3D STL/GLB、数控 CNC G 代码与 IATF 16949 首检单。

为了方便大家免去本地配置环境的麻烦，我们搭建了纯静态的在线 3D 演示站（完全在浏览器端运行），内置了 STM32 工业四层板与空调主控板两个典型案例：
👉 **免安装 3D 在线体验**：https://mo9652962-ai.github.io/wave-fixture-ai/

（注：为保护您的板卡涉密安全，在线站只提供公开样例试玩；企业私有图纸可在本地开发机或车间工控机直接运行 `uvx wave-fixture-ai` 纯离线使用，数据 100% 留在本地。）

GitHub 仓库（MIT 开源，371 项测试全绿）：
https://github.com/mo9652962-ai/wave-fixture-ai
欢迎各位工友试用拍砖！
```

---

## 场景三：知乎 / B 站动态 / 视频评论区

### 知乎回答契合话题
- *“如何评价电子工程师的工作日常？”*
- *“做硬件开发有哪些相见恨晚的神仙工具？”*
- *“PCBA 波峰焊治具应该如何设计？”*

### 知乎发布模版
> 手工在 AutoCAD 里面对着 Gerber 描波峰焊治具，绝对是电子研发和制造工艺里面最枯燥、最容易因看走眼而撞件报废的脏活。  
> 
> 我们最近把这套繁琐工序开源自动化了：把 Gerber 或 KiCad 工程拖进去，沉板外扩、狗骨头 R1.85 自动清角、迎锡面 60° 倒流倒角、Ersa 防浮渣槽、薄壁纯钛刀片嵌件全部毫秒级算好，还带 71 项 DRC 制造门禁（遇到危险壁厚或机台超限自动打 PREVIEW 水印防误投）。  
> 
> 最爽的是连环境都不用装，搭了一个纯前端的 3D 体验站，点进去就能 360° 拖动旋转治具，看继电器和大电容是怎么被红色报警盒标出来的：  
> 🔗 **在线 3D 玩玩看**：https://mo9652962-ai.github.io/wave-fixture-ai/  
> 
> 涉密工程支持终端一行跑离线版：`uvx wave-fixture-ai`，连代码都不用 git clone。  
> 开源地址：github.com/mo9652962-ai/wave-fixture-ai

---

## 场景四：Twitter / X 极速卡片

### Tweet 文本
```text
Don't write another line of manual CAD for wave soldering pallets. 

We built a 100% open-source CAM engine that takes your KiCad / Gerber and generates 3D pallets, 73 DRC gates & CNC G-code in seconds.

Play with the zero-friction interactive 3D demo right in your browser (no install needed):
👉 https://mo9652962-ai.github.io/wave-fixture-ai/

Offline CLI: `uvx wave-fixture-ai`
⭐ GitHub: https://github.com/mo9652962-ai/wave-fixture-ai

#KiCad #PCBDesign #Hardware #CAM #Manufacturing #OpenSource
```

---

## 场景五：Reddit 简明回帖卡片（在已有求助贴下回帖）

```text
Check out https://mo9652962-ai.github.io/wave-fixture-ai/
It's an open-source tool (MIT) that automatically calculates wave pallet sink pockets, dogbone corner reliefs, 60° wave chamfers, and dross skimmers directly from KiCad / Gerber files. 
The demo above runs purely client-side with 3D rotation and interference checks. You can also run it locally offline via `uvx wave-fixture-ai`.
```
