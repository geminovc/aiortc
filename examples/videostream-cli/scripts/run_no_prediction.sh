video_name=$1
record_name=$2
experiment_dir=$(pwd)

#kill $(pgrep -f 'python3')
mkdir -p ${record_name}

export CONFIG_PATH='/data4/pantea/aiortc/nets_implementation/first_order_model/config/resolution1024_vpx.yaml'

echo "Starting sender"
python3 cli.py offer \
--play-from ${video_name} \
--signaling-path test.sock \
--signaling unix-socket \
--quantizer 63 \
--save-dir ${record_name} \
--verbose 2>${record_name}/sender.log &

sleep 15 

echo "Starting receiver"
python3 cli.py answer \
--record-to ${record_name}/received.mp4 \
--signaling-path test.sock \
--signaling unix-socket \
--save-dir ${record_name} \
--verbose 2>${record_name}/receiver.log

for end_point in sender receiver 
do	
	cd /data4/pantea/nets_scripts/post_experiment_process
	python /data4/pantea/nets_scripts/post_experiment_process/plot_bw_trace_vs_estimation.py \
                    --log-path ${experiment_dir}/${record_name}/${end_point}.log \
		    --trace-path /data4/pantea/nets_scripts/traces/12mbps_trace \
                    --save-dir ${experiment_dir}/${record_name} \
		    --output-name link_vs_sent_vs_estimation_${end_point} \
		    --window 500

	python /data4/pantea/nets_scripts/post_experiment_process/estimate_bw_at_sender.py \
		--log-path ${experiment_dir}/${record_name}/${end_point}.log \
		--save-dir ${experiment_dir}/${record_name} \
		--output-name bw_${end_point} \
		--trace-path /data4/pantea/nets_scripts/traces/fixed/96mbps_trace
	
	python /data4/pantea/nets_scripts/post_experiment_process/estimate_rtt_at_sender.py \
		--log-path ${experiment_dir}/${record_name}/${end_point}.log \
		--save-dir ${experiment_dir}/${record_name} \
		--output-name rtt_${end_point}
done

cd /data4/pantea/nets_scripts/post_experiment_process

python compare_video_quality_from_numpy.py \
        --save-dir ${experiment_dir}/${record_name} \
        --numpy-prefix-1 ${experiment_dir}/${record_name}/sender_frame \
        --numpy-prefix-2 ${experiment_dir}/${record_name}/receiver_frame \
        --output-name hr_visual_metrics.txt \

#python compare_video_quality_from_videofile.py \
#        --video-path-1 ${video_name} \
#        --video-path-2 ${experiment_dir}/${record_name}/received.mp4 \
#        --save-dir ${experiment_dir}/${record_name} \
#       --output-name hr_visual_metrics_from_video.txt \

echo "Done"

