# PTCGP YOLO OBB 模型

PTCGP (Pokemon TCG Pocket) 卡牌检测专用模型，基于 YOLO11 Nano OBB 训练。

## 模型说明

### yolo11n-5k-25-2026.02.02

**命名规则：**
- `yolo11n` - 基础模型 (YOLO11 Nano)
- `5k` - 使用 5000 张合成数据集训练
- `25` - 训练 25 个 epochs
- `2026.02.02` - 训练完成日期

**训练参数：**

| 参数 | 值 |
|------|------|
| 任务类型 | OBB (Oriented Bounding Box) |
| 基础模型 | yolo11n-obb.pt |
| 数据集 | data/synthetic/data.yaml |
| 数据集大小 | 5000 张合成图片 |
| 训练轮数 | 25 epochs |
| Batch大小 | 16 |
| 输入尺寸 | 640x640 |
| 优化器 | auto (SGD) |
| 学习率 | 0.01 |
| 设备 | CPU |

**性能指标：**

| 指标 | 数值 |
|------|------|
| mAP50 | **0.995** |
| mAP50-95 | **0.995** |
| Precision | **1.0** |
| Recall | **1.0** |
| 模型大小 | 5.5 MB |

**优势：**
- 使用更大的数据集（5000张），泛化能力更强
- 完美指标：Precision 1.0，Recall 1.0
- 适合生产环境使用

## 文件说明

- `best.pt` - 训练得到的最佳模型权重 (PyTorch格式, 5.5 MB)
- `best.mlpackage` - CoreML 格式模型 (iOS/macOS原生支持, 5.3 MB)
- `args.yaml` - 完整的训练参数配置
- `results.csv` - 每轮训练的详细指标记录
- `results.png` - 训练过程可视化图表
- `confusion_matrix.png` - 混淆矩阵

## 使用说明

### 加载模型（PyTorch）

```python
from ultralytics import YOLO

# 加载模型
model = YOLO('models/yolo11n-5k-25-2026.02.02/best.pt')

# 进行预测
results = model('your_image.jpg')
```

### 加载模型（CoreML - macOS/iOS 推荐）

```python
from ultralytics import YOLO

# CoreML 格式推理速度更快（约2.4倍）
model = YOLO('models/yolo11n-5k-25-2026.02.02/best.mlpackage')
results = model('your_image.jpg')
```

## 性能对比

| 格式 | 推理时间 | 推荐场景 |
|------|----------|----------|
| PyTorch (.pt) | ~24ms | 开发调试 |
| CoreML (.mlpackage) | ~10ms | 生产环境 |

## 注意事项

- 此模型专为 PTCGP (Pokemon TCG Pocket) 游戏卡牌检测设计
- 使用 OBB (旋转边界框) 检测，支持倾斜卡牌
- 建议置信度阈值：0.6-0.7
- 训练数据集为合成数据，包含网格模式和随机模式
- CoreML 格式使用 Apple Neural Engine (ANE) 加速

## 技术细节

**模型架构：** YOLO11 Nano OBB
- 层数：110 layers
- 参数量：2,653,918
- GFLOPs：6.6

**检测能力：**
- 支持卡牌旋转角度检测
- 可处理密集排列场景（网格模式训练）
- 支持小目标检测（最小缩放 0.08）
