#!/bin/bash
video_name=$1
record_name=$2
python3 cli.py offer \
--play-from ${video_name} \
--signaling-path test.sock \
--signaling unix-socket \
--verbose 2>${record_name}/sender.log
