import os

first_order_model_configs = '/data1/pantea/aiortc/nets_implementation/first_order_model/config/paper_configs'
final_checkpoints_base = '/video-conf/scratch/vibhaa_tardy/final_results/training_with_encoder'

config_paths = {
    64: f'{first_order_model_configs}/resolution_comparison/lr64_tgt45Kb.yaml',
    128 : f'{first_order_model_configs}/exps_overview/lr128_tgt15Kb.yaml',
    256: f'{first_order_model_configs}/exps_overview/lr256_tgt75Kb.yaml',
    512: f'{first_order_model_configs}/exps_overview/lr512_tgt180Kb.yaml'
}

checkpoint_zoo = {
        'xiran' :{
            64: '/video-conf/scratch/vibhaa_tardy/encoder_fixed_bitrate/xiran1024_lr64_tgt45Kb 06_09_22_01.59.42/00000029-checkpoint.pth.tar',
            128 : '/video-conf/scratch/vibhaa_tardy/encoder_fixed_bitrate/xiran1024_lr128_tgt45Kb 06_09_22_01.59.09/00000029-checkpoint.pth.tar',
            256: '/video-conf/scratch/vibhaa_tardy/encoder_fixed_bitrate/xiran1024_lr256_tgt75Kb 05_09_22_02.35.02/00000029-checkpoint.pth.tar',
            512: ''
            },

        'kayleigh' :{
            64: '/00000029-checkpoint.pth.tar',
            128 : '/video-conf/scratch/vibhaa_lam2/encoder_fixed_bitrate/kayleigh1024_128lr_tgt15Kb 08_09_22_01.37.16/00000029-checkpoint.pth.tar',
            256: '/video-conf/scratch/vibhaa_lam2/encoder_fixed_bitrate/kayleigh1024_256lr_tgt105Kb 08_09_22_01.36.04/00000029-checkpoint.pth.tar',
            512: '/video-conf/scratch/vibhaa_lam2/encoder_fixed_bitrate/kayleigh1024_512lr_tgt180Kb 08_09_22_22.11.57/00000014-checkpoint.pth.tar'
            },

        'needle_drop' :{
            64: f'{final_checkpoints_base}/lr64_tgt45/needle_drop/00000029-checkpoint.pth.tar',
            128 : f'{final_checkpoints_base}/lr128_tgt15/needle_drop/00000029-checkpoint.pth.tar',
            256: f'{final_checkpoints_base}/lr256_tgt45/needle_drop/00000029-checkpoint.pth.tar',
            512: f'{final_checkpoints_base}/lr512_tgt180/needle_drop/00000029-checkpoint.pth.tar'
            },
}
