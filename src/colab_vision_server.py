import sys
import logging
import os
import io
from concurrent import futures
import grpc
# from timeit import default_timer as timer
import time
# from time import perf_counter_ns as timer, process_time_ns as cpu_timer
from time import time as timer
import uuid
import pickle
import blosc2 as blosc
import numpy as np
from PIL import Image

sys.path.append(".")
parent = os.path.abspath('.')
sys.path.insert(1, parent)

import alexnet_pytorch_split as alex
from test_data import test_data_loader as data_loader

from . import colab_vision
from . import colab_vision_pb2
from . import colab_vision_pb2_grpc

class FileServer(colab_vision_pb2_grpc.colab_visionServicer):
    def __init__(self):

        class Servicer(colab_vision_pb2_grpc.colab_visionServicer):
            def __init__(self):
                self.tmp_folder = './temp/'
                self.model = alex.Model()
                # self.model = Model()

            def constantInference(self, request_iterator, context):
                #unpack msg contents
                current_chunks = []
                last_id = None
                for i, msg in enumerate(request_iterator):
                    print(f"Message received with id {msg.id}. Responding with Dummy.")
                    m = colab_vision_pb2.Response_Dict(
                            id = f"reply to{msg.id}",
                            results = str(i).encode(),
                            actions = msg.action
                        )
                    m.keypairs.append(colab_vision_pb2.Response_Dict.Keypair())
                    m.keypairs["test"] = 1 #not sure if this can even be done on instantiation
                    yield m

            def constantInference_1(self, request_iterator, context):
                #unpack msg contents
                current_chunks = []
                last_id = None
                for msg in request_iterator:
                    if colab_vision_pb2.ACT_END in msg.action:
                        break #exit
                    if colab_vision_pb2.ACT_RESET in msg.action:
                        #reset operation regardless of current progress
                        current_chunks = []
                        last_id = msg.id
                    if msg.id == last_id:
                        current_chunks.append(msg.chunk)
                        #continue the same inference
                    else:
                        current_chunks = [].append(msg.chunk)
                    #continue the same inference
                    if colab_vision_pb2.ACT_APPEND in msg.action: 
                        #convert chunks into object and save at appropriate layer
                        current_chunks = save_chunks_to_object(current_chunks)
                        if colab_vision_pb2.ACT_COMPRESSED in msg.action: # decompress
                            current_chunks = blosc.unpack_tensor(current_chunks)
                        pass #not yet implemented
                    if colab_vision_pb2.ACT_INFERENCE in msg.action:
                        #convert chunks into object and perform inference
                        partial_inf_tensor = colab_vision.get_object_chunks(current_chunks)
                        if colab_vision_pb2.ACT_COMPRESSED in msg.action: # decompress
                            partial_inf_tensor = blosc.unpack_tensor(partial_inf_tensor)
                        prediction = self.model.predict(partial_inf_tensor, start_layer=msg.layer)
                        print(f"Inference completed for {msg.id}. Result {prediction}")
                    # print(f"Message received with id {msg.id}. Responding.")
                        yield colab_vision_pb2.Response_Dict(
                                id = str(prediction),
                                keypairs = None,
                                results = None,
                                actions = None
                            )
      
                    
                #deal with chunks

                #do flag actions

        logging.basicConfig()
        self.server = grpc.server(futures.ThreadPoolExecutor(max_workers=2))
        colab_vision_pb2_grpc.add_colab_visionServicer_to_server(Servicer(), self.server)

    def start(self, port):
        self.server.add_insecure_port(f'[::]:{port}')
        self.server.start()
        print("Server started.")
        self.server.wait_for_termination()