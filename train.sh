CUDA_VISIBLE_DEVICES=4,5,6,7 \
python train.py ./dataset/train/ \
--mindepth 0.5 \
--pretrained-dps ./checkpoints/train/05-08-05:30/dpsnet_5_checkpoint.pth.tar \
--nlabel 64 \
--log-output \
