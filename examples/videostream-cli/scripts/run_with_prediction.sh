
video_name=$1
record_name=$2

#kill $(pgrep -f 'python3')
mkdir -p ${record_name}

echo "Starting sender"
python3 cli.py offer \
--play-from ${video_name} \
--signaling-path test.sock \
--signaling unix-socket \
--enable-prediction \
--verbose 2>${record_name}/sender.log &

sleep 15 

echo "Starting receiver"
python3 cli.py answer \
--record-to ${record_name}/received.mp4 \
--signaling-path test.sock \
--signaling unix-socket \
--enable-prediction \
--verbose 2>${record_name}/receiver.log

experiment_dir=$(pwd)
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

echo "Done"

