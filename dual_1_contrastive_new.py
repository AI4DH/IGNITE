# -*- coding: utf-8 -*-
"""
Created on Fri Aug 26 17:25:30 2022

@author: gghos
"""

import tensorflow.compat.v1 as tf
tf.compat.v1.disable_v2_behavior()

import os

from Contrastivelosslayer import nt_xent_loss
from utils import ones_target, zeros_target
import numpy as np
import seaborn as sns 
import pandas as pd
import matplotlib.pyplot as plt
import random
import math

class IGNITE(object):
    def __init__(self, sess,
                 # -- shared params:
                 batch_size, time_steps,
                 num_pre_epochs, 
                 checkpoint_dir,
                 # -- params for observed-only-vae
                 oo_vae_dim, 
                #  c_noise_dim,
                 z_size,observed_only_data_sample,
                 observed_only_vae,
                 # -- params for imm-vae
                 imm_vae_dim, IMM_data_sample,
                 IMM_vae, 
                 binary_mask_data_sample,experiment_name,
                 conditional=False, num_labels=0,
                 interventions=None):

        self.sess = sess
        self.batch_size = batch_size
        self.time_steps = time_steps
        self.num_pre_epochs = num_pre_epochs
        self.checkpoint_dir = checkpoint_dir
        self.interventions = interventions
        self.experiment_name = experiment_name

        # params for observed_only-VAE
        self.oo_vae_dim = oo_vae_dim
        self.z_size = z_size
        self.observed_only_data_sample =observed_only_data_sample
        self.observed_only_vae_net = observed_only_vae

        # params for IMM-VAE
        self.imm_vae_dim = imm_vae_dim
        self.IMM_data_sample = IMM_data_sample
        self.IMM_vae_net = IMM_vae

        self.binary_mask_data_sample = binary_mask_data_sample

        # params for interventions information
        self.num_labels = num_labels
        self.conditional = conditional
        self.name = "logs/last/"+self.experiment_name


    def build(self):
        self.build_tf_graph()
        self.build_loss()
        self.build_summary()
        self.saver = tf.train.Saver()

    def save(self, global_id, model_name=None, checkpoint_dir=None):
        self.saver.save(self.sess, os.path.join(
            checkpoint_dir, model_name), global_step=global_id)

    def load(self, model_name=None, checkpoint_dir=None):
        ckpt = tf.train.get_checkpoint_state(checkpoint_dir)
        ckpt_name = os.path.basename(ckpt.model_checkpoint_path)
        self.saver.restore(self.sess, os.path.join(checkpoint_dir, ckpt_name))
        global_id = int(ckpt_name[len(model_name) + 1:])
        return global_id

    def embed_vis(self, embedding_var, type):
        saving_dir = self.name

    
        metadata_file = os.path.join(saving_dir, 'metadata_classes.tsv')
        with open(metadata_file, 'w') as f:
            f.write("patient_status\tpatient_status1\n")
            for i in range(embedding_var.shape[0]):
                c1 = self.interventions[i, 0]   # patient status
                f.write("%s\t%s\n" % (c1, c1))
        f.close()

        """Setup for Tensorboard embedding visualization"""
        config = tf.contrib.tensorboard.plugins.projector.ProjectorConfig()
        embed = config.embeddings.add()
        embed.tensor_name = embedding_var.name
        embed.metadata_path = os.path.join('', 'metadata_classes.tsv')
        tf.contrib.tensorboard.plugins.projector.visualize_embeddings(self.summary_writer, config)
        saver_images = tf.train.Saver([embedding_var])
        saver_images.save(self.sess, os.path.join(saving_dir, 'embeddings.ckpt'))

        
    def build_tf_graph(self):
     
        if self.conditional:
            self.real_data_label_pl = tf.placeholder(
                dtype=float, shape=[self.batch_size,self.time_steps, self.num_labels], name="real_data_label")
                
        self.observed_only_real_data_pl = tf.placeholder(
            dtype=float, shape=[self.batch_size, self.time_steps, self.oo_vae_dim], name="observed_only_real_data")
        self.observed_only_real_data_binary_mask_pl = tf.placeholder(
            dtype=float, shape=[self.batch_size, self.time_steps, self.oo_vae_dim], name="observed_only_real_binary_mask")


        if self.conditional:
            self.observed_only_decoded_output, self.observed_only_vae_sigma, self.observed_only_vae_mu, self.observed_only_vae_logsigma, self.c_enc_z = \
                self.observed_only_vae_net.build_vae(self.observed_only_real_data_pl, self.real_data_label_pl)
        else:
            self.observed_only_decoded_output, self.observed_only_vae_sigma, self.observed_only_vae_mu, self.observed_only_vae_logsigma, self.c_enc_z = \
                self.observed_only_vae_net.build_vae(self.observed_only_real_data_pl)


        self.IMM_real_data_pl = tf.placeholder(
            dtype=float, shape=[self.batch_size, self.time_steps, self.imm_vae_dim], name="real_personalized")
        if self.conditional:
            self.IMM_decoded_output, self.IMM_vae_sigma, self.IMM_vae_mu, self.IMM_vae_logsigma, self.d_enc_z = \
                self.IMM_vae_net.build_vae(self.IMM_real_data_pl, self.real_data_label_pl)
        else:
            self.IMM_decoded_output, self.IMM_vae_sigma, self.IMM_vae_mu, self.IMM_vae_logsigma, self.d_enc_z = \
                self.IMM_vae_net.build_vae(self.IMM_real_data_pl)
                
                

        
        m_binary_mask = tf.cast(self.observed_only_real_data_binary_mask_pl, tf.bool) #observed values
        binary_masked_observed_only_decoded_output_observed = tf.where(m_binary_mask, self.IMM_decoded_output, tf.zeros_like(self.IMM_decoded_output))  
        self.real = self.IMM_vae_net.build_Discriminator(binary_masked_observed_only_decoded_output_observed)

        
        
        
    
        gen_binary_mask =  tf.logical_not(m_binary_mask)
        binary_masked_observed_only_decoded_output_imputed = tf.where(gen_binary_mask, self.IMM_decoded_output, tf.zeros_like(self.IMM_decoded_output))  
        self.generated = self.IMM_vae_net.build_Discriminator(binary_masked_observed_only_decoded_output_imputed)
        
        
  
    

    def build_loss(self):

        #################
        # (1) VAE loss  #
        #################
        alpha_re = 1
        alpha_kl = 0.75
        alpha_mt = 0.001
        alpha_ct =0.001
        alpha_discrim = 1

        x_latent_1 = tf.stack(self.c_enc_z, axis=1)
        x_latent_2 = tf.stack(self.d_enc_z, axis=1)
        self.vae_matching_loss = tf.losses.mean_squared_error(x_latent_1, x_latent_2)

        self.vae_contra_loss = nt_xent_loss(tf.reshape(x_latent_1, [x_latent_1.shape[0], -1]),
                                            tf.reshape(x_latent_2, [x_latent_2.shape[0], -1]), self.batch_size)

                    
        # HERE
        m_binary_mask = tf.cast(self.observed_only_real_data_binary_mask_pl, tf.bool)
        binary_masked_observed_only_real_data_pl = tf.where(m_binary_mask, self.observed_only_real_data_pl, tf.zeros_like(self.observed_only_real_data_pl))  
        binary_masked_observed_only_decoded_output = tf.where(m_binary_mask, self.observed_only_decoded_output, tf.zeros_like(self.observed_only_decoded_output))  

        self.observed_only_re_loss = tf.losses.mean_squared_error(binary_masked_observed_only_real_data_pl, binary_masked_observed_only_decoded_output)
    
        observed_only_kl_loss = [0] * self.time_steps 
        for t in range(self.time_steps):
            observed_only_kl_loss[t] = 0.5 * (tf.reduce_sum(self.observed_only_vae_sigma[t], 1) + tf.reduce_sum(
                tf.square(self.observed_only_vae_mu[t]), 1) - tf.reduce_sum(self.observed_only_vae_logsigma[t] + 1, 1))
        
        self.observed_only_kl_loss = tf.reduce_mean(tf.add_n(observed_only_kl_loss))
        if self.conditional:
            self.observed_only_vae_loss = alpha_re*self.observed_only_re_loss + \
                            alpha_kl*self.observed_only_kl_loss
                  
        else:
            self.observed_only_vae_loss = alpha_re*self.observed_only_re_loss + \
                            alpha_kl*self.observed_only_kl_loss 
                          
        
        self.IMM_re_loss = alpha_re* tf.losses.mean_squared_error(self.IMM_real_data_pl, self.IMM_decoded_output)
        IMM_kl_loss = [0] * self.time_steps
        for t in range(self.time_steps):
            IMM_kl_loss[t] = 0.5 * (tf.reduce_sum(self.IMM_vae_sigma[t], 1) + tf.reduce_sum(
                tf.square(self.IMM_vae_mu[t]), 1) - tf.reduce_sum(self.IMM_vae_logsigma[t] + 1, 1))
        self.IMM_kl_loss = alpha_kl * tf.reduce_mean(tf.add_n(IMM_kl_loss))
        
        #discriminator loss
        self.dicrete_d_loss_real = tf.reduce_mean(tf.nn.sigmoid_cross_entropy_with_logits(
           logits=self.real, labels=ones_target(self.batch_size, min=0.8, max=0.9)))
        self.dicrete_d_loss_fake = tf.reduce_mean(tf.nn.sigmoid_cross_entropy_with_logits(
          logits=self.generated, labels=zeros_target(self.batch_size, min=0.1, max=0.1)))
        self.discriminator_loss = self.dicrete_d_loss_real + self.dicrete_d_loss_fake

        if self.conditional:
            self.IMM_vae_loss = alpha_re*self.IMM_re_loss + \
                            alpha_kl*self.IMM_kl_loss + \
                             alpha_mt* self.vae_matching_loss + \
                            alpha_ct* self.vae_contra_loss  + self.discriminator_loss
                     
        else:
            self.IMM_vae_loss = alpha_re*self.IMM_re_loss + \
                            alpha_kl*self.IMM_kl_loss + \
                               alpha_mt* self.vae_matching_loss + \
                               alpha_ct*self.vae_contra_loss  + alpha_discrim*self.discriminator_loss  
  
      

        #######################
        # Optimizer           #
        #######################
        t_vars = tf.trainable_variables()
        observed_only_vae_vars = [var for var in t_vars if 'observed_only_VAE' in var.name]
        s_vae_vars = [var for var in t_vars if 'Shared_VAE' in var.name]

        IMM_vae_vars = [var for var in t_vars if 'IMM_VAE' in var.name]

        self.oo_v_op_pre = tf.train.AdamOptimizer(learning_rate=0.0005)\
            .minimize(self.observed_only_vae_loss, var_list=observed_only_vae_vars)

        self.imm_v_op_pre = tf.train.AdamOptimizer(learning_rate=0.0005)\
            .minimize(self.IMM_vae_loss, var_list=IMM_vae_vars)


    def build_summary(self):
        print("finalize")
        self.observed_only_vae_summary = []
        self.observed_only_vae_summary.append(tf.summary.scalar("observed_only_loss/reconstruction_loss", self.observed_only_re_loss))
        self.observed_only_vae_summary.append(tf.summary.scalar("observed_only_loss/kl_divergence_loss", self.observed_only_kl_loss))
        self.observed_only_vae_summary.append(tf.summary.scalar("observed_only_loss/matching_loss", self.vae_matching_loss))
        self.observed_only_vae_summary.append(tf.summary.scalar("observed_only_loss/contrastive_loss", self.vae_contra_loss))

        self.observed_only_vae_summary.append(tf.summary.scalar("observed_only_loss/vae_loss", self.observed_only_vae_loss))
        self.observed_only_vae_summary = tf.summary.merge(self.observed_only_vae_summary)

        self.IMM_vae_summary = []
        self.IMM_vae_summary.append(tf.summary.scalar("IMM_VAE_loss/reconstruction_loss", self.IMM_re_loss))
        self.IMM_vae_summary.append(tf.summary.scalar("IMM_VAE_loss/kl_divergence_loss", self.IMM_kl_loss))
        self.IMM_vae_summary.append(tf.summary.scalar("IMM_VAE_loss/matching_loss", self.vae_matching_loss))
        self.IMM_vae_summary.append(tf.summary.scalar("IMM_VAE_loss/contrastive_loss", self.vae_contra_loss))
        self.IMM_vae_summary.append(tf.summary.scalar("IMM_VAE_loss/discriminator_loss", self.discriminator_loss))
        self.IMM_vae_summary.append(tf.summary.scalar("IMM_VAE_loss/vae_loss", self.IMM_vae_loss))
        self.IMM_vae_summary = tf.summary.merge(self.IMM_vae_summary)
 
    def train(self):
        self.summary_writer = tf.summary.FileWriter(self.name, self.sess.graph)

       
        observed_only_x = self.observed_only_data_sample[: int(self.observed_only_data_sample.shape[0]), :, :]

        binary_mask_x = self.binary_mask_data_sample[: int(self.binary_mask_data_sample.shape[0]), :, :]
        
        IMM_x = self.IMM_data_sample[: int(self.IMM_data_sample.shape[0]), :, :]

        if self.conditional:
            label_data = self.interventions[: int(self.IMM_data_sample.shape[0]), :, :]
        data_size = observed_only_x.shape[0]
        num_batches = math.ceil(data_size // self.batch_size)
        print("data_size", data_size)

        tf.global_variables_initializer().run()

        print('start training')
        global_id = 0

        for pre in range(self.num_pre_epochs):
            observed_only_x_random = observed_only_x
            IMM_x_random = IMM_x
            binary_mask_x_random = binary_mask_x
            if self.conditional:
                label_data_random = label_data
         
            print("VAE epoch %d" % pre)

            observed_only_real_data_lst = []
            observed_only_rec_data_lst = []
            IMM_real_data_lst = []
            IMM_rec_data_lst = []
       
            for b in range(num_batches):

                feed_dict = {}
                feed_dict[self.observed_only_real_data_pl] = observed_only_x_random[b * self.batch_size: (b + 1) * self.batch_size]
                feed_dict[self.IMM_real_data_pl] = IMM_x_random[b * self.batch_size: (b + 1) * self.batch_size]
                feed_dict[self.observed_only_real_data_binary_mask_pl] = binary_mask_x_random[b * self.batch_size: (b + 1) * self.batch_size]
        
                if self.conditional:
                    feed_dict[self.real_data_label_pl] = label_data_random[b * self.batch_size: (b + 1) * self.batch_size]

                summary_result, _ = self.sess.run([self.observed_only_vae_summary, self.oo_v_op_pre], feed_dict=feed_dict)
                self.summary_writer.add_summary(summary_result, global_id)
                summary_result, _ = self.sess.run([self.IMM_vae_summary, self.imm_v_op_pre], feed_dict=feed_dict)
                self.summary_writer.add_summary(summary_result, global_id)
                
               


                observed_only_real_data, observed_only_rec_data, d_binary_mask = self.sess.run([self.observed_only_real_data_pl, self.observed_only_decoded_output, self.observed_only_real_data_binary_mask_pl], feed_dict=feed_dict)
                observed_only_real_data_lst.append(observed_only_real_data)
                observed_only_rec_data_lst.append(observed_only_rec_data)

                IMM_real_data, IMM_rec_data,d_binary_mask= self.sess.run([self.IMM_real_data_pl, self.IMM_decoded_output, self.observed_only_real_data_binary_mask_pl], feed_dict=feed_dict)
                IMM_real_data_lst.append(IMM_real_data)
                IMM_rec_data_lst.append(IMM_rec_data)

                assert not np.any(np.isnan(IMM_real_data))

                assert not np.any(np.isnan(IMM_rec_data))

                global_id += 1
           
            print(len(IMM_rec_data_lst))      
        np.savez('data/'+self.experiment_name+'.npz', observed_only_real=np.vstack(observed_only_real_data_lst), observed_only_rec=np.vstack(observed_only_rec_data_lst),
                                     IMM_real=np.vstack(IMM_real_data_lst), IMM_rec=np.vstack(IMM_rec_data_lst))
        save_path = os.path.join(self.checkpoint_dir, "train_vae_{}".format(global_id))
        if not os.path.exists(save_path):
            os.makedirs(save_path)
        self.save(global_id=global_id - 1, model_name='IGNITE', checkpoint_dir=save_path)
        print('finished model training')

