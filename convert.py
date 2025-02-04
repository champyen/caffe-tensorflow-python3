#!/usr/bin/env python3

import os
import sys
import argparse

import shutil
import pickle
import tensorflow as tf
from tensorflow.python.tools.freeze_graph import freeze_graph
from tensorflow.python.tools import optimize_for_inference_lib

from kaffe import KaffeError, print_stderr
from kaffe.tensorflow import TensorFlowTransformer


def fatal_error(msg):
    print_stderr(msg)
    exit(-1)


def validate_arguments(args):
    if (args.data_output_path is not None) and (args.caffemodel is None):
        fatal_error('No input data path provided.')
    if (args.caffemodel is not None) and (args.data_output_path is None) and \
        (args.standalone_output_path is None):
        fatal_error('No output data path provided.')
    if (args.code_output_path is None) and (args.data_output_path is None) and \
        (args.standalone_output_path is None):
        fatal_error('No output path specified.')


def convert(def_path, caffemodel_path, data_output_path, code_output_path, standalone_output_path,
            phase, freeze):
    try:
        sess = tf.InteractiveSession()
        transformer = TensorFlowTransformer(def_path, caffemodel_path, phase=phase)
        print_stderr('Converting data...')
        if data_output_path is not None:
            data = transformer.transform_data()
            print_stderr('Saving data...')
            with open(data_output_path, 'wb') as handle:
                pickle.dump(data, handle, protocol=pickle.HIGHEST_PROTOCOL)
        if code_output_path is not None:
            print_stderr('Saving source...')
            with open(code_output_path, 'w') as src_out:
                src_out.write(transformer.transform_source())

        if standalone_output_path:
            filename, _ = os.path.splitext(os.path.basename(standalone_output_path))
            temp_folder = os.path.join(os.path.dirname(standalone_output_path), '.tmp')
            if not os.path.exists(temp_folder):
                os.makedirs(temp_folder)
                shutil.rmtree(temp_folder) # Delete old graphs

            if data_output_path is None:
                data = transformer.transform_data()
                print_stderr('Saving data...')
                data_output_path = os.path.join(temp_folder, filename) + '.npy'
                with open(data_output_path, 'wb') as handle:
                    pickle.dump(data, handle, protocol=pickle.HIGHEST_PROTOCOL)

            if code_output_path is None:
                print_stderr('Saving source...')
                code_output_path = os.path.join(temp_folder, filename) + '.py'
                with open(code_output_path, 'wb') as src_out:
                    src_out.write(transformer.transform_source())

            checkpoint_path = os.path.join(temp_folder, filename + '.ckpt')
            graph_name = os.path.basename(standalone_output_path)
            graph_folder = os.path.dirname(standalone_output_path)
            input_node = transformer.graph.nodes[0].name
            output_node = transformer.graph.nodes[-1].name
            tensor_shape = transformer.graph.get_node(input_node).output_shape
            tensor_shape_list = [tensor_shape.batch_size, tensor_shape.height,
                                 tensor_shape.width, tensor_shape.channels]

            sys.path.append(os.path.dirname(code_output_path))
            module = os.path.splitext(os.path.basename(code_output_path))[0]
            class_name = transformer.graph.name
            KaffeNet = getattr(__import__(module), class_name)

            data_placeholder = tf.compat.v1.placeholder(
                tf.float32, tensor_shape_list, name=input_node)
            net = KaffeNet({input_node: data_placeholder})

            # load weights stored in numpy format
            net.load(data_output_path, sess)

            print_stderr('Saving checkpoint...')
            saver = tf.compat.v1.train.Saver()
            saver.save(sess, checkpoint_path)

            print_stderr('Saving graph definition as protobuf...')
            tf.io.write_graph(sess.graph.as_graph_def(), graph_folder, graph_name, False)
            writer = tf.compat.v1.summary.FileWriter('.tmp', sess.graph)
            writer.close()

            input_graph_path = standalone_output_path
            input_saver_def_path = ""
            input_binary = True
            input_checkpoint_path = checkpoint_path
            output_node_names = output_node
            restore_op_name = 'save/restore_all'
            filename_tensor_name = 'save/Const:0'
            output_graph_path = standalone_output_path
            clear_devices = True

            print_stderr('Saving standalone model...')
            output_node_names = '{0}/{0}'.format(output_node_names)
            if freeze == 'freeze_graph':
                freeze_graph(input_graph_path, input_saver_def_path,
                             input_binary, input_checkpoint_path,
                             output_node_names, restore_op_name,
                             filename_tensor_name, output_graph_path,
                             clear_devices, '')
            elif freeze == 'optimize_for_inference':
                graph_def = sess.graph.as_graph_def()
                graph_def = tf.graph_util.convert_variables_to_constants(
                    sess, graph_def, [output_node_names])
                graph_def_f32 = optimize_for_inference_lib.optimize_for_inference(
                    graph_def, ['data'], [output_node_names], tf.float32.as_datatype_enum)
                tf.train.write_graph(
                    graph_def_f32, "", standalone_output_path.rsplit('.',1)[0] + '.pb', as_text=False)
                tf.train.write_graph(
                    graph_def_f32, "", standalone_output_path.rsplit('.',1)[0] + '.pbtxt', as_text=True)

            #f = shutil.rmtree(temp_folder)
            writer = tf.compat.v1.summary.FileWriter('.tmp', sess.graph)
            writer.close()

        print_stderr('Done.')
    except KaffeError as err:
        fatal_error('Error encountered: {}'.format(err))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('def_path', help='Model definition (.prototxt) path')
    parser.add_argument('--caffemodel', help='Model data (.caffemodel) path')
    parser.add_argument('--data-output-path', help='Converted data output path')
    parser.add_argument('--code-output-path', help='Save generated source to this path')
    parser.add_argument('--standalone-output-path',
                        help='Save generated standalone tensorflow model to this path')
    parser.add_argument('-p',
                        '--phase',
                        default='test',
                        help='The phase to convert: test (default) or train')
    parser.add_argument('-fz',
                        '--freeze',
                        default=None,
                        help="""Freeze option for inference: No (default),
                                freeze_graph or optimize_for_inference(e.g. for OpenCV)""")
    args = parser.parse_args()
    validate_arguments(args)
    convert(args.def_path, args.caffemodel, args.data_output_path, args.code_output_path,
            args.standalone_output_path, args.phase, args.freeze)


if __name__ == '__main__':
    main()
