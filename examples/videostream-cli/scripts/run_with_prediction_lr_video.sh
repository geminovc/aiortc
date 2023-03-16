video_name=$1
record_name=$2

#1 export CHECKPOINT_PATH='/video-conf/scratch/vibhaa_tardy/xiran1024_with_lr_video_64features_with_l1loss 27_06_22_13.25.38/00000099-checkpoint.pth.tar'

#1 export CONFIG_PATH='/data4/pantea/aiortc/nets_implementation/first_order_model/config/xiran1024_with_lr_video_64features_with_l1loss_27_06_22_13.25.38_resolution1024_with_sr_changed.yaml'

#2 export CHECKPOINT_PATH='/video-conf/scratch/vibhaa_tardy/lr_features_in_decoder/xiran1024_with_lr_video_32features 25_04_22_09.58.48/00000099-checkpoint.pth.tar'
#2 export CONFIG_PATH='/data4/pantea/aiortc/nets_implementation/first_order_model/config/xiran1024_with_lr_video_32features_25_04_22_09.58.48_resolution1024_with_sr_changed.yaml'

#export CHECKPOINT_PATH='/video-conf/scratch/vibhaa_tardy/3occlusion_masks/xiran1024_with_lr_hourglass_and_3occlusion_masks_7x7kernel_on_lr_with_softmax 04_08_22_19.32.55/00000099-checkpoint.pth.tar'
#export CONFIG_PATH='/video-conf/scratch/vibhaa_tardy/3occlusion_masks/xiran1024_with_lr_hourglass_and_3occlusion_masks_7x7kernel_on_lr_with_softmax 04_08_22_19.32.55/resolution1024_with_sr.yaml'


## encoder in fixed quantization training below


export CHECKPOINT_PATH='/video-conf/scratch/vibhaa_tardy/with_encoder_in_training/xiran1024_with_512x512lr_quant63_7x7LRkernel 22_08_22_15.17.34/00000079-checkpoint.pth.tar'
export CONFIG_PATH='/video-conf/scratch/vibhaa_tardy/with_encoder_in_training/xiran1024_with_512x512lr_quant63_7x7LRkernel 22_08_22_15.17.34/resolution1024_with_sr.yaml'

#export CHECKPOINT_PATH='/video-conf/scratch/vibhaa_tardy/with_encoder_in_training/xiran1024_with_256x256lr_quant48_7x7LRkernel 16_08_22_19.57.52/00000099-checkpoint.pth.tar'
#export CONFIG_PATH='/video-conf/scratch/vibhaa_tardy/with_encoder_in_training/xiran1024_with_256x256lr_quant48_7x7LRkernel 16_08_22_19.57.52/resolution1024_with_sr.yaml'

#export CHECKPOINT_PATH='/video-conf/scratch/vibhaa_tardy/with_encoder_in_training/xiran1024_with_256x256lr_quant55_7x7LRkernel 22_08_22_15.18.42/00000099-checkpoint.pth.tar'
#export CONFIG_PATH='/video-conf/scratch/vibhaa_tardy/with_encoder_in_training/xiran1024_with_256x256lr_quant55_7x7LRkernel 22_08_22_15.18.42/resolution1024_with_sr.yaml'

#export CHECKPOINT_PATH='/video-conf/scratch/vibhaa_tardy/with_encoder_in_training/xiran1024_with_128x128lr_quant32_7x7LRkernel 16_08_22_19.53.56/00000099-checkpoint.pth.tar'
#export CONFIG_PATH='/video-conf/scratch/vibhaa_tardy/with_encoder_in_training/xiran1024_with_128x128lr_quant32_7x7LRkernel 16_08_22_19.53.56/resolution1024_with_sr.yaml'

#export CHECKPOINT_PATH='/video-conf/scratch/vibhaa_tardy/with_encoder_in_training/xiran1024_with_128x128lr_quant45_7x7LRkernel 14_08_22_03.27.54/00000099-checkpoint.pth.tar'
#export CONFIG_PATH='/video-conf/scratch/vibhaa_tardy/with_encoder_in_training/xiran1024_with_128x128lr_quant45_7x7LRkernel 14_08_22_03.27.54/resolution1024_with_sr.yaml'

#export CHECKPOINT_PATH='/video-conf/scratch/vibhaa_tardy/with_encoder_in_training/xiran1024_with_128x128lr_quant28_7x7LRkernel 18_08_22_18.39.57/00000099-checkpoint.pth.tar'
#export CONFIG_PATH='/video-conf/scratch/vibhaa_tardy/with_encoder_in_training/xiran1024_with_128x128lr_quant28_7x7LRkernel 18_08_22_18.39.57/resolution1024_with_sr.yaml'

#export CHECKPOINT_PATH='/video-conf/scratch/vibhaa_tardy/with_encoder_in_training/xiran1024_with_64x64lr_quant32_7x7LRkernel 14_08_22_02.55.44/00000099-checkpoint.pth.tar'
#export CONFIG_PATH='/video-conf/scratch/vibhaa_tardy/with_encoder_in_training/xiran1024_with_64x64lr_quant32_7x7LRkernel 14_08_22_02.55.44/resolution1024_with_sr.yaml'

#export CHECKPOINT_PATH='/video-conf/scratch/vibhaa_tardy/with_encoder_in_training/xiran1024_with_64x64lr_quant16_7x7LRkernel 14_08_22_03.28.08/00000099-checkpoint.pth.tar'
#export CONFIG_PATH='/video-conf/scratch/vibhaa_tardy/with_encoder_in_training/xiran1024_with_64x64lr_quant16_7x7LRkernel 14_08_22_03.28.08/resolution1024_with_sr.yaml'

#export CHECKPOINT_PATH='/video-conf/scratch/vibhaa_tardy/with_encoder_in_training/xiran1024_with_64x64lr_quant12_7x7LRkernel 16_08_22_19.56.17/00000099-checkpoint.pth.tar'
#export CONFIG_PATH='/video-conf/scratch/vibhaa_tardy/with_encoder_in_training/xiran1024_with_64x64lr_quant12_7x7LRkernel 16_08_22_19.56.17/resolution1024_with_sr.yaml'


## encoder in random quantization training below


#export CHECKPOINT_PATH='/video-conf/scratch/vibhaa_tardy/with_encoder_in_training/xiran1024_with_64x64lr_random_quant_7x7LRkernel 22_08_22_15.15.10/00000099-checkpoint.pth.tar'
#export CONFIG_PATH='/video-conf/scratch/vibhaa_tardy/with_encoder_in_training/xiran1024_with_64x64lr_random_quant_7x7LRkernel 22_08_22_15.15.10/resolution1024_with_sr.yaml'

echo $CHECKPOINT_PATH
echo $CONFIG_PATH

#kill $(pgrep -f 'python3')
mkdir -p ${record_name}
ref_freq=2000
echo reference frequency ${ref_freq}

echo "Starting sender"
python3 cli.py offer \
--play-from ${video_name} \
--signaling-path test.sock \
--signaling unix-socket \
--enable-prediction \
--prediction-type use_low_res_video \
--quantizer 32 \
--lr-quantizer 59 \
--reference-update-freq ${ref_freq} \
--save-dir ${record_name} \
--verbose 2>${record_name}/sender.log &

sleep 20 

echo "Starting receiver"
python3 cli.py answer \
--record-to ${record_name}/received.mp4 \
--signaling-path test.sock \
--signaling unix-socket \
--enable-prediction \
--prediction-type use_low_res_video \
--reference-update-freq ${ref_freq} \
--save-dir ${record_name} \
--verbose 2>${record_name}/receiver.log

experiment_dir=$(pwd)
for end_point in sender receiver 
do
	echo ${end_point}
	cd /data4/pantea/nets_scripts/post_experiment_process
	python /data4/pantea/nets_scripts/post_experiment_process/plot_bw_trace_vs_estimation.py \
                    --log-path ${experiment_dir}/${record_name}/${end_point}.log \
		    --trace-path /data4/pantea/nets_scripts/traces/12mbps_trace \
                    --save-dir ${experiment_dir}/${record_name} \
		    --output-name ${end_point} \
		    --window 500

	python /data4/pantea/nets_scripts/post_experiment_process/estimate_rtt_at_sender.py \
		--log-path ${experiment_dir}/${record_name}/${end_point}.log \
		--save-dir ${experiment_dir}/${record_name} \
		--output-name ${end_point}
done
cd /data4/pantea/nets_scripts/post_experiment_process

python compare_video_quality_from_numpy.py \
	--save-dir ${experiment_dir}/${record_name} \
	--numpy-prefix-1 ${experiment_dir}/${record_name}/sender_lr_frame \
	--numpy-prefix-2 ${experiment_dir}/${record_name}/receiver_lr_frame \
	--output-name lr_visual_metrics.txt \
	--make-video

python compare_video_quality_from_numpy.py \
        --save-dir ${experiment_dir}/${record_name} \
        --numpy-prefix-1 ${experiment_dir}/${record_name}/sender_frame \
        --numpy-prefix-2 ${experiment_dir}/${record_name}/predicted_frame \
        --output-name hr_visual_metrics.txt \
#        --make-video

#python compare_video_quality.py \
#        --video-path-1 /data4/pantea/aiortc/examples/videostream-cli/encoder_experiments/lowest_bitrate/original.mp4 \
#        --video-path-2 ${experiment_dir}/${record_name}/received.mp4 \
#        --save-dir ${experiment_dir}/${record_name} \

