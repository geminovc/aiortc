video_name=$1
record_name=$2


export CONFIG_PATH='/data4/pantea/aiortc/nets_implementation/first_order_model/config/resolution1024_bicubic.yaml'

#kill $(pgrep -f 'python3')
mkdir -p ${record_name}

echo "Starting sender"
python3 cli.py offer \
--play-from ${video_name} \
--signaling-path test.sock \
--signaling unix-socket \
--enable-prediction \
--prediction-type bicubic \
--reference-update-freq 20 \
--lr-quantizer 48 \
--save-dir ${record_name} \
--verbose 2>${record_name}/sender.log &

sleep 25 

echo "Starting receiver"
python3 cli.py answer \
--record-to ${record_name}/received.mp4 \
--signaling-path test.sock \
--signaling unix-socket \
--enable-prediction \
--prediction-type bicubic \
--reference-update-freq 20 \
--save-dir ${record_name} \
--verbose 2>${record_name}/receiver.log

experiment_dir=$(pwd)
for end_point in sender 
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
#	--make-video

#python compare_video_quality.py \
#        --video-path-1 /data4/pantea/aiortc/examples/videostream-cli/encoder_experiments/lowest_bitrate/original.mp4 \
#        --video-path-2 ${experiment_dir}/${record_name}/received.mp4 \
#        --save-dir ${experiment_dir}/${record_name} \

