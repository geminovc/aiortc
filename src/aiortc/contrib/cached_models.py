cfg_base = '/data4/pantea/aiortc/nets_implementation/first_order_model/config/paper_configs'
ckp_base = '/video-conf/scratch/vibhaa_tardy/final_results/training_with_encoder'

settings = [(128, 15), (256, 45), (256, 75), (256, 105), (512, 180), (512, 420)]
people = ['needle_drop']
config_paths = {}
checkpoint_zoo = {}
for person in people:
    checkpoint_zoo[person] = {}

for setting in settings:
    lr_size, bitrate = setting
    config_paths[(lr_size, int(1000 * bitrate))] = f'{cfg_base}/exps_overview/lr{lr_size}_tgt{bitrate}Kb.yaml'
    for person in ['needle_drop']:
        checkpoint_zoo[person][(lr_size, int(1000 * bitrate))] = f'{ckp_base}/lr{lr_size}_tgt{bitrate}Kb/{person}/00000029-checkpoint.pth.tar'
