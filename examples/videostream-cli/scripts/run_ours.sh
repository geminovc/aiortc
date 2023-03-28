video_name=$1
record_name=$2
process=$3
uplink_trace=/data4/pantea/nets_scripts/traces/paper_ours  #/video-conf/scratch/pantea_mapmaker/traces/paper_ours_shrink
downlink_trace=/data4/pantea/nets_scripts/traces/fixed/12mbps.mahi
window=1000
trap "trap - SIGTERM && kill -- -$$" SIGINT SIGTERM EXIT

cd ..

if [ $process != 'process' ]
then
	if [ -d $record_name ]
	then
		# check not to overwrite
		echo "Directory exists!" $record_name
		exit
	fi

	mkdir -p ${record_name}
	mkdir -p ${record_name}/plots_sender
	mkdir -p ${record_name}/plots_receiver

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

experiment_dir=$(pwd)

mm-graph ${experiment_dir}/${record_name}/mahimahi.log 100 --no-port --yrange \"0:2\" --no-display --plot-direction \
		egress > ${experiment_dir}/${record_name}/mahimahi.eps 2> ${experiment_dir}/${record_name}/mmgraph.log

for end_point in sender
do
	cd /data4/pantea/nets_scripts/post_experiment_process
	python3 /data4/pantea/nets_scripts/post_experiment_process/plot_bw_trace_vs_estimation.py \
		--log-dir ${experiment_dir}/${record_name} \
		--end-point ${end_point} \
		--trace-path $uplink_trace \
		--save-dir ${experiment_dir}/${record_name}/plots_${end_point} \
		--output-name ${end_point} \
		--window $window

	python3 get_metrics_timeseries.py \
        	    --template-output ${experiment_dir}/${record_name}/plots_${end_point}/timeseries_${end_point}_w${window}_ms.csv \
                    --save-dir ${experiment_dir}/${record_name}/plots_${end_point} \
       		    --video-path-1 ${video_name} \
                    --video-path-2 ${experiment_dir}/${record_name}/received.mp4 \
                   --window ${window}
done

echo "Done"

