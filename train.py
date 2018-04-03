# -*- coding: utf-8 -*-
"""Learning rates comparison - CNN

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1ynqfIQK9HgbAHqaED6mBxAVEP2MMsHhb
"""

#   Copyright 2016 The TensorFlow Authors. All Rights Reserved.
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
"""Convolutional Neural Network Estimator for MNIST, built with tf.layers."""

import time
from datetime import datetime
import traceback
import uuid
import shutil
import os
import argparse

import numpy as np
import tensorflow as tf

from ploty import Ploty
from hooks import *



class Model(object):

    def __init__(self, optimizer_fn, val_target=0.99, max_mins=100, scale=1, output_path="/tmp/", train_callback=None, eval_callback=None):
        self.optimizer_fn = optimizer_fn
        self.val_target = val_target
        self.max_mins = max_mins
        self.scale = scale
        self.output_path = output_path
        self.train_callback = train_callback
        self.eval_callback = eval_callback
        self.start_time = time.time()

    def cnn_model_fn(self, features, labels, mode):
        """Model function for CNN."""
        tf.set_random_seed(3141592)
        
        # Input Layer
        # Reshape X to 4-D tensor: [batch_size, width, height, channels]
        # MNIST images are 28x28 pixels, and have one color channel
        input_layer = tf.reshape(features["x"], [-1, 28, 28, 1])

        # Convolutional Layer #1
        # Computes 32 features using a 5x5 filter with ReLU activation.
        # Padding is added to preserve width and height.
        # Input Tensor Shape: [batch_size, 28, 28, 1]
        # Output Tensor Shape: [batch_size, 28, 28, 32]
        conv1 = tf.layers.conv2d(
            inputs=input_layer,
            filters=round(32*self.scale),
            kernel_size=[5, 5],
            padding="same",
            activation=tf.nn.relu)

        # Pooling Layer #1
        # First max pooling layer with a 2x2 filter and stride of 2
        # Input Tensor Shape: [batch_size, 28, 28, 32]
        # Output Tensor Shape: [batch_size, 14, 14, 32]
        pool1 = tf.layers.max_pooling2d(inputs=conv1, pool_size=[2, 2], strides=2)

        # Convolutional Layer #2
        # Computes 64 features using a 5x5 filter.
        # Padding is added to preserve width and height.
        # Input Tensor Shape: [batch_size, 14, 14, 32]
        # Output Tensor Shape: [batch_size, 14, 14, 64]
        conv2 = tf.layers.conv2d(
            inputs=pool1,
            filters=round(64 * self.scale),
            kernel_size=[5, 5],
            padding="same",
            activation=tf.nn.relu)

        # Pooling Layer #2
        # Second max pooling layer with a 2x2 filter and stride of 2
        # Input Tensor Shape: [batch_size, 14, 14, 64]
        # Output Tensor Shape: [batch_size, 7, 7, 64]
        pool2 = tf.layers.max_pooling2d(inputs=conv2, pool_size=[2, 2], strides=2)

        # Flatten tensor into a batch of vectors
        # Input Tensor Shape: [batch_size, 7, 7, 64]
        # Output Tensor Shape: [batch_size, 7 * 7 * 64]
        pool2_flat = tf.reshape(pool2, [-1, 7 * 7 * round(self.scale* 64)])

        # Dense Layer
        # Densely connected layer with 1024 neurons
        # Input Tensor Shape: [batch_size, 7 * 7 * 64]
        # Output Tensor Shape: [batch_size, 1024]
        dense = tf.layers.dense(inputs=pool2_flat, units=round(1024*self.scale), activation=tf.nn.relu)

        # Add dropout operation; 0.6 probability that element will be kept
        dropout = tf.layers.dropout(
            inputs=dense, rate=0.4, training=mode == tf.estimator.ModeKeys.TRAIN)

        # Logits layer
        # Input Tensor Shape: [batch_size, 1024]
        # Output Tensor Shape: [batch_size, 10]
        logits = tf.layers.dense(inputs=dropout, units=10)

        predictions = {
            # Generate predictions (for PREDICT and EVAL mode)
            "classes": tf.argmax(input=logits, axis=1),
            # Add `softmax_tensor` to the graph. It is used for PREDICT and by the
            # `logging_hook`.
            "probabilities": tf.nn.softmax(logits, name="softmax_tensor")
        }

        # Add evaluation metrics (for EVAL mode)
        eval_metric_ops = {
          "accuracy": tf.metrics.accuracy(
              labels=labels, predictions=predictions["classes"])
        }


        # Hooks
        early_stop = EarlyStopping(
          eval_metric_ops["accuracy"], 
          start_time=self.start_time,
          target=self.val_target, 
          check_every=1,
          max_mins=self.max_mins)

        train_hooks = [early_stop]
        eval_hooks = []

        if self.train_callback is not None:
          m = MetricHook(eval_metric_ops["accuracy"], self.train_callback)
          train_hooks.append(m)

        if self.eval_callback is not None:
          m = MetricHook(eval_metric_ops["accuracy"], self.eval_callback)
          eval_hooks.append(m)

        ### Create EstimatorSpecs ###

        if mode == tf.estimator.ModeKeys.PREDICT:
            return tf.estimator.EstimatorSpec(mode=mode, predictions=predictions)

        # Calculate Loss (for both TRAIN and EVAL modes)
        loss = tf.losses.sparse_softmax_cross_entropy(labels=labels, logits=logits)

        # Configure the Training Op (for TRAIN mode)
        if mode == tf.estimator.ModeKeys.TRAIN:
          global_step = tf.train.get_global_step()
          self.optimizer = self.optimizer_fn(global_step)
          train_op = self.optimizer.minimize(
              loss=loss,
              global_step=global_step)

          return tf.estimator.EstimatorSpec(
            mode=mode, 
            loss=loss,
            train_op=train_op,
            training_hooks=train_hooks)

        if mode == tf.estimator.ModeKeys.EVAL:
          return tf.estimator.EstimatorSpec(
            mode=mode, 
            loss=loss, 
            eval_metric_ops=eval_metric_ops, 
            evaluation_hooks=eval_hooks)


    def train_and_evaluate(self, train_steps_total=100, eval_throttle_secs=200):
        
        # Load training and eval data
        mnist = tf.contrib.learn.datasets.load_dataset("mnist")
        train_data = mnist.train.images # Returns np.array
        train_labels = np.asarray(mnist.train.labels, dtype=np.int32)
        eval_data = mnist.test.images   # Returns np.array
        eval_labels = np.asarray(mnist.test.labels, dtype=np.int32)
        
        # Create a model
        # This lambda hack removes the self reference
        model_fn = lambda features, labels, mode: self.cnn_model_fn(
            features, labels, mode)

        # Create the Estimator
        model_dir = self.output_path + str(uuid.uuid1())
        mnist_classifier = tf.estimator.Estimator(
            model_fn=model_fn, model_dir=model_dir)


        # Data input functions
        train_input_fn = tf.estimator.inputs.numpy_input_fn(
            x={"x": train_data},
            y=train_labels,
            batch_size=100,
            num_epochs=None,
            shuffle=True)

        eval_input_fn = tf.estimator.inputs.numpy_input_fn(
            x={"x": eval_data},
            y=eval_labels,
            num_epochs=1,
            shuffle=False)


        # Specs for train and eval
        train_spec = tf.estimator.TrainSpec(input_fn=train_input_fn, max_steps=train_steps_total)
        eval_spec = tf.estimator.EvalSpec(input_fn=eval_input_fn, throttle_secs=eval_throttle_secs)

        tf.estimator.train_and_evaluate(mnist_classifier, train_spec, eval_spec)

        test_results = mnist_classifier.evaluate(input_fn=eval_input_fn)
        print(test_results)

        try:
          shutil.rmtree(model_dir)
        except:
          pass
      
      
def LRRange(mul=5):
  
  for i in range(mul*6, 0, -1):
    lr = pow(0.1, i/mul)
    yield lr

  for i in range(1, 2*mul+1):
    lr = pow(10, i/mul)
    yield lr
    
    
def lr_schedule(optimizer, starter_learning_rate=0.1, 
                global_step=None, mode="fixed", 
                decay_rate=0.96, decay_steps=100, 
                cycle_lr_decay=0.001, cycle_length=1000):
  
  if mode == "fixed":
    return optimizer(starter_learning_rate)
  
  elif mode == "exp_decay":
    lr = tf.train.exponential_decay(starter_learning_rate, global_step,
                                    decay_steps, decay_rate, staircase=True)
    return optimizer(lr)
  
  elif mode == "cosine_restart":
    lr = tf.train.cosine_decay_restarts(
      starter_learning_rate,
      global_step,
      cycle_length,
      alpha=cycle_lr_decay)
    
    return optimizer(lr)
  
  elif mode == "triangle":
  
    min_lr = starter_learning_rate * cycle_lr_decay
  
    cycle = tf.floor(1+global_step/(2*cycle_length))
    x = tf.abs(global_step/cycle_length - 2*cycle + 1)
    lr = starter_learning_rate + (starter_learning_rate-min_lr)*tf.maximum(0, (1-x))/float(2**(cycle-1))



output_path = "/tmp/"

optimizers = {
    "Adam": tf.train.AdamOptimizer,
    "Adagrad": tf.train.AdagradOptimizer,
    "Momentum": lambda lr: tf.train.MomentumOptimizer(lr, 0.5),
    "GD": tf.train.GradientDescentOptimizer,
    "Adadelta": tf.train.AdadeltaOptimizer,
    "RMSProp": tf.train.RMSPropOptimizer,  
}

ideal_lr = {
  "Adam": 0.001,
  "Adagrad": 0.1,
  "Momentum": 0.2,
  "GD": 0.2,
  "Adadelta": 4,
  "RMSProp": 0.001,  
}

schedules = [
#   "exp_decay", 
  "fixed", 
#   "cosine_restart"
]


def run(optimizer="Adam", schedule="fixed", lr=0.01, scale=1, max_mins=2, train_callback=None, eval_callback=None, eval_throttle_secs=5):

    opt = optimizers[optimizer]

    def get_optimizer(global_step):
        return lr_schedule(opt, lr, global_step=global_step, mode=schedule)

    m = Model(
      optimizer_fn=get_optimizer, 
      val_target=0.97, 
      max_mins=max_mins, 
      scale=scale,
      train_callback=train_callback,
      eval_callback=eval_callback)

    m.train_and_evaluate(eval_throttle_secs=eval_throttle_secs)


def plt_time_to_train(FLAGS):
    p = Ploty(output_path=FLAGS.output_dir, title="Time to train vs learning rate", x="Learning rate",log_x=True, log_y=True)
    for opt in optimizers.keys():
      for sched in schedules:
        for lr in LRRange(6):
          try:
            print(f"Running {opt} {sched} {lr}")

            def cb(r):
              p.add_result(lr, r["time_taken"], opt + " " + sched, data=r)

            r = run(opt, sched, lr, scale=FLAGS.scale, max_mins=FLAGS.max_mins, eval_callback=cb)

          except Exception:
            traceback.print_exc()
            pass

      try:
        p.copy_to_drive()  
      except Exception:
        tf.logging.error(e)
        pass

def plt_time_vs_model_size(FLAGS):

    oversample = FLAGS.oversample
    
    p = Ploty(output_path=FLAGS.output_dir,title="Time to train vs size of model",x="Model scale",clear_screen=True)
    for opt in optimizers.keys():
      for sched in schedules:
        for i in range(1*oversample, 10*oversample):
          scale = i/oversample
          try:

            def cb(r):
              print(r, opt, sched, scale)
              if r["accuracy"] >= 0.96:
                p.add_result(scale, r["time_taken"], opt + " " + sched, data=r)
              else:
                tf.logging.error("Failed to train.")

            r = run(opt, sched, ideal_lr[opt], scale=scale, max_mins=FLAGS.max_mins, eval_callback=cb)        

          except Exception:
            traceback.print_exc()
            pass
          
      try:
        p.copy_to_drive()  
      except:
        pass



def plt_train_trace(FLAGS):
    p = Ploty(
      output_path=FLAGS.output_dir, 
      title="Validation accuracy over time", 
      x="Time",
      y="Validation accuracy",
      log_x=True, 
      log_y=True,
      legend=True)

    sched = "fixed"
    
    for opt in optimizers.keys():

      lr = ideal_lr[opt]

      try:
        tf.logging.info(f"Running {opt} {sched} {lr}")

        time_start = time.time()

        def cb(mode):
          def d(acc):
            taken = time.time() - time_start
            p.add_result(taken, acc, opt+"-"+mode)
          return d

        r = run(opt, sched, lr, scale=FLAGS.scale, max_mins=FLAGS.max_mins, train_callback=cb("train"), eval_callback=cb("eval"), eval_throttle_secs=5)
        
       
      except Exception:
        traceback.print_exc()
        pass


if __name__ == "__main__":

  tf.logging.set_verbosity('INFO')

  parser = argparse.ArgumentParser()
  parser.add_argument('--max-mins', type=float, default=2)
  parser.add_argument('--scale', type=int, default=3)
  parser.add_argument('--oversample', type=int, default=4)
  parser.add_argument('--output-dir', type=str, default="./output")

  FLAGS = parser.parse_args()


  tf.logging.info("starting...")

  # plt_time_to_train(FLAGS)
  # plt_time_vs_model_size(FLAGS)
  plt_train_trace(FLAGS)

