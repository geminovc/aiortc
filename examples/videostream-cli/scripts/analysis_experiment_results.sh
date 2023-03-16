video_name=$1
record_name=$2

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

# 	python /data4/pantea/nets_scripts/post_experiment_process/estimate_bw_at_sender.py \
#               --log-path ${experiment_dir}/${record_name}/${end_point}.log \
#               --save-dir ${experiment_dir}/${record_name} \
#               --output-name bw_${end_point} \
#               --trace-path /data4/pantea/nets_scripts/traces/fixed/96mbps_trace

done

cd /data4/pantea/nets_scripts/post_experiment_process

#python compare_video_quality_from_numpy.py \
#        --save-dir ${experiment_dir}/${record_name} \
#        --numpy-prefix-1 ${experiment_dir}/${record_name}/sender_lr_frame \
#        --numpy-prefix-2 ${experiment_dir}/${record_name}/receiver_lr_frame \
#        --output-name lr_visual_metrics.txt \
#        --make-video

python compare_video_quality_from_numpy.py \
        --save-dir ${experiment_dir}/${record_name} \
        --numpy-prefix-1 ${experiment_dir}/${record_name}/sender_frame \
        --numpy-prefix-2 ${experiment_dir}/${record_name}/predicted_frame \
        --output-name hr_visual_metrics.txt \
        --make-video

#python compare_video_quality_from_videofile.py \
#        --video-path-1 ${video_name} \
#        --video-path-2 ${experiment_dir}/${record_name}/received.mp4 \
#        --save-dir ${experiment_dir}/${record_name} \
#	--output-name hr_visual_metrics_from_video.txt \


