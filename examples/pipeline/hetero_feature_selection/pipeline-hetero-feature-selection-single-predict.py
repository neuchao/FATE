#
#  Copyright 2019 The FATE Authors. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#
import argparse

from pipeline.backend.pipeline import PipeLine
from pipeline.component import DataTransform
from pipeline.component import FeatureScale
from pipeline.component import FederatedSample
from pipeline.component import HeteroFeatureBinning
from pipeline.component import HeteroFeatureSelection
from pipeline.component import Intersection
from pipeline.component import Reader
from pipeline.interface import Data
from pipeline.interface import Model
from pipeline.utils.tools import load_job_config


def main(config="../../config.yaml", namespace=""):
    # obtain config
    if isinstance(config, str):
        config = load_job_config(config)

    parties = config.parties
    guest = parties.guest[0]
    host = parties.host[0]

    guest_train_data = {"name": "breast_hetero_guest", "namespace": f"experiment{namespace}"}
    host_train_data = {"name": "breast_hetero_host", "namespace": f"experiment{namespace}"}

    guest_eval_data = {"name": "breast_hetero_guest", "namespace": f"experiment{namespace}"}
    host_eval_data = {"name": "breast_hetero_host", "namespace": f"experiment{namespace}"}

    # initialize pipeline
    pipeline = PipeLine()
    # set job initiator
    pipeline.set_initiator(role="guest", party_id=guest)
    # set participants information
    pipeline.set_roles(guest=guest, host=host)

    # define Reader components to read in data
    reader_0 = Reader(name="reader_0")
    # configure Reader for guest
    reader_0.get_party_instance(role="guest", party_id=guest).component_param(table=guest_train_data)
    # configure Reader for host
    reader_0.get_party_instance(role="host", party_id=host).component_param(table=host_train_data)

    # define DataTransform components
    data_transform_0 = DataTransform(name="data_transform_0")  # start component numbering at 0

    # get DataTransform party instance of guest
    data_transform_0_guest_party_instance = data_transform_0.get_party_instance(role="guest", party_id=guest)
    # configure DataTransform for guest
    data_transform_0_guest_party_instance.component_param(with_label=True, output_format="dense")
    # get and configure DataTransform party instance of host
    data_transform_0.get_party_instance(role="host", party_id=host).component_param(with_label=False)

    # define Intersection components
    intersection_0 = Intersection(
        name="intersection_0",
        intersect_method="rsa",
        rsa_params={"hash_method": "sha256", "final_hash_method": "sha256", "key_length": 1024})
    pipeline.add_component(reader_0)
    pipeline.add_component(data_transform_0, data=Data(data=reader_0.output.data))
    pipeline.add_component(intersection_0, data=Data(data=data_transform_0.output.data))

    reader_1 = Reader(name="reader_1")
    reader_1.get_party_instance(role="guest", party_id=guest).component_param(table=guest_eval_data)
    reader_1.get_party_instance(role="host", party_id=host).component_param(table=host_eval_data)
    data_transform_1 = DataTransform(name="data_transform_1")
    intersection_1 = Intersection(
        name="intersection_1",
        intersect_method="rsa",
        rsa_params={"hash_method": "sha256", "final_hash_method": "sha256", "key_length": 1024})

    pipeline.add_component(reader_1)
    pipeline.add_component(
        data_transform_1, data=Data(
            data=reader_1.output.data), model=Model(
            data_transform_0.output.model))
    pipeline.add_component(intersection_1, data=Data(data=data_transform_1.output.data))

    sample_0 = FederatedSample(name="sample_0", fractions=0.9)
    pipeline.add_component(sample_0, data=Data(data=intersection_0.output.data))

    binning_param = {
        "method": "quantile",
        "compress_thres": 10000,
        "head_size": 10000,
        "error": 0.001,
        "bin_num": 10,
        "bin_indexes": -1,
        "bin_names": None,
        "category_indexes": None,
        "category_names": None,
        "adjustment_factor": 0.5,
        "local_only": False,
        "encrypt_param": {
            "key_length": 1024
        },
        "transform_param": {
            "transform_cols": -1,
            "transform_names": None,
            "transform_type": "bin_num"
        }
    }
    hetero_feature_binning_0 = HeteroFeatureBinning(name="hetero_feature_binning_0", **binning_param)
    pipeline.add_component(hetero_feature_binning_0, data=Data(data=sample_0.output.data))

    hetero_feature_binning_1 = HeteroFeatureBinning(name="hetero_feature_binning_1")
    pipeline.add_component(hetero_feature_binning_1,
                           data=Data(data=intersection_1.output.data),
                           model=Model(hetero_feature_binning_0.output.model))

    selection_param = {
        "select_col_indexes": -1,
        "select_names": [],
        "filter_methods": [
            "manually",
            "iv_value_thres",
            "iv_percentile"
        ],
        "manually_param": {
            "filter_out_indexes": [],
            "filter_out_names": []
        },
        "unique_param": {
            "eps": 1e-06
        },
        "iv_value_param": {
            "value_threshold": 0.1
        },
        "iv_percentile_param": {
            "percentile_threshold": 0.9
        },
        "variance_coe_param": {
            "value_threshold": 0.3
        },
        "outlier_param": {
            "percentile": 0.95,
            "upper_threshold": 2.0
        }
    }
    hetero_feature_selection_0 = HeteroFeatureSelection(name="hetero_feature_selection_0", **selection_param)
    pipeline.add_component(hetero_feature_selection_0,
                           data=Data(data=hetero_feature_binning_0.output.data),
                           model=Model(isometric_model=[hetero_feature_binning_0.output.model]))

    hetero_feature_selection_1 = HeteroFeatureSelection(name="hetero_feature_selection_1")
    pipeline.add_component(hetero_feature_selection_1,
                           data=Data(data=hetero_feature_binning_1.output.data),
                           model=Model(hetero_feature_selection_0.output.model))

    scale_0 = FeatureScale(name="scale_0")
    scale_1 = FeatureScale(name="scale_1")

    pipeline.add_component(scale_0, data=Data(data=hetero_feature_selection_0.output.data))
    pipeline.add_component(scale_1, data=Data(data=hetero_feature_selection_1.output.data),
                           model=Model(scale_0.output.model))
    pipeline.compile()
    pipeline.fit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser("PIPELINE DEMO")
    parser.add_argument("-config", type=str,
                        help="config file")
    args = parser.parse_args()
    if args.config is not None:
        main(args.config)
    else:
        main()
