video_name=$1
record_name=$2
process=$3
uplink_trace=/data4/pantea/nets_scripts/traces/paper_ours_shrink_1M  #/video-conf/scratch/pantea_mapmaker/traces/paper_ours_shrink
downlink_trace=/data4/pantea/nets_scripts/traces/fixed/12mbps.mahi
window=1000
trap "trap - SIGTERM && kill -- -$$" SIGINT SIGTERM EXIT
#kill $(pgrep -f 'python3')
cd ..
mkdir -p ${record_name}
mkdir -p ${record_name}/plots_sender
mkdir -p ${record_name}/plots_receiver

if [ $process != 'process' ]
then
echo "Starting sender"
mm-delay 25 mm-link --uplink-log=${record_name}/mahimahi.log --uplink-queue=droptail --uplink-queue-args=bytes=1000000 $uplink_trace $downlink_trace ./offer_ours.sh  ${video_name} ${record_name} &
#./offer.sh  ${video_name} ${record_name} &

sleep 30 

echo "Starting receiver"
CUDA_VISIBLE_DEVICES=1 python3 cli.py answer \
--record-to ${record_name}/received.mp4 \
--signaling-path test.sock \
--signaling unix-socket \
--enable-prediction \
--prediction-type use_low_res_video \
--reference-update-freq 300000 \
--lr-enable-gcc \
--verbose 2>${record_name}/receiver.log
fi

mm-graph ${record_name}/mahimahi.log 60 --no-port

experiment_dir=$(pwd)
for end_point in sender
do
	cd /data4/pantea/nets_scripts/post_experiment_process
	python3 /data4/pantea/nets_scripts/post_experiment_process/plot_bw_trace_vs_estimation.py \
                    --log-path ${experiment_dir}/${record_name}/${end_point}.log \
		    --trace-path $uplink_trace \
                    --save-dir ${experiment_dir}/${record_name}/plots_${end_point} \
		    --output-name ${end_point} \
		    --window $window

	python3 get_metrics_timeseries.py \
        	    --template-output ${experiment_dir}/${record_name}/plots_${end_point}/compression_timeseries_${end_point}_w${window}_ms.csv \
                    --save-dir ${experiment_dir}/${record_name}/plots_${end_point} \
       		    --video-path-1 ${video_name} \
                    --video-path-2 ${experiment_dir}/${record_name}/received.mp4 \
                   --window ${window}

#	python /data4/pantea/nets_scripts/post_experiment_process/estimate_bw_at_sender.py \
#		--log-path ${experiment_dir}/${record_name}/${end_point}.log \
#		--save-dir ${experiment_dir}/${record_name} \
#		--output-name bw_${end_point} \
#		--trace-path /data4/pantea/nets_scripts/traces/fixed/96mbps_trace
	
#	python /data4/pantea/nets_scripts/post_experiment_process/estimate_rtt_at_sender.py \
#		--log-path ${experiment_dir}/${record_name}/${end_point}.log \
#		--save-dir ${experiment_dir}/${record_name} \
#		--output-name rtt_${end_point}
done

echo "Done"

