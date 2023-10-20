from fate.ml.nn.model_zoo.hetero_nn_model import HeteroNNModelGuest, HeteroNNModelHost
from fate.ml.nn.hetero.hetero_nn import HeteroNNTrainerGuest, HeteroNNTrainerHost, TrainingArguments
from fate.ml.nn.model_zoo.agg_layer.plaintext_agg_layer import InteractiveLayerGuest, InteractiveLayerHost
from fate.ml.nn.hetero.hetero_nn import HeteroNNTrainerGuest, HeteroNNTrainerHost
import sys
from datetime import datetime
import pandas as pd
from torch.utils.data import TensorDataset, DataLoader
import tqdm


def get_current_datetime_str():
    return datetime.now().strftime("%Y-%m-%d-%H-%M")


guest = ("guest", "10000")
host = ("host", "9999")
name = get_current_datetime_str()


def create_ctx(local, context_name):
    from fate.arch import Context
    from fate.arch.computing.standalone import CSession
    from fate.arch.federation.standalone import StandaloneFederation
    import logging

    # prepare log
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    # init fate context
    computing = CSession()
    return Context(
        computing=computing, federation=StandaloneFederation(computing, context_name, local, [guest, host])
    )


if __name__ == "__main__":

    party = sys.argv[1]
    import torch as t


    def set_seed(seed):
        t.manual_seed(seed)
        if t.cuda.is_available():
            t.cuda.manual_seed_all(seed)
            t.backends.cudnn.deterministic = True
            t.backends.cudnn.benchmark = False


    class HeteroNNLocalModel(t.nn.Module):

        def __init__(self, guest_b, guest_t, host_b, guest_i, host_i):
            super(HeteroNNLocalModel, self).__init__()
            self._guest_b = guest_b
            self._guest_t = guest_t
            self._host_b = host_b
            self._guest_i = guest_i
            self._host_i = host_i
        def forward(self, x_g, x_h):
            fw_g = self._guest_i(self._guest_b(x_g))
            fw_h = self._host_i(self._host_b(x_h))
            fw_ = fw_g + fw_h
            fw_ = t.nn.ReLU()(fw_)
            fw_ = self._guest_t(fw_)
            return fw_

    set_seed(42)

    batch_size = 64
    epoch = 10
    guest_bottom = t.nn.Linear(10, 4).double()
    guest_top = t.nn.Sequential(
                                 t.nn.Linear(4, 1),
                                 t.nn.Sigmoid()
                               ).double()
    host_bottom = t.nn.Linear(20, 4).double()

    # # make random fake data
    sample_num = 569

    if party == "guest":

        ctx = create_ctx(guest, get_current_datetime_str())
        df = pd.read_csv('/home/cwj/FATE/FATE-2.0/FATE/examples/data/breast_hetero_guest.csv')
        X_g = t.Tensor(df.drop(columns=['id', 'y']).values).type(t.float64)[0: sample_num]
        y = t.Tensor(df['y'].values).type(t.float64)[0: sample_num].reshape((-1, 1))

        dataset = TensorDataset(X_g, y)

        interactive_layer = InteractiveLayerGuest(4,4,4)
        loss_fn = t.nn.BCELoss()

        model = HeteroNNModelGuest(
            top_model=guest_top,
            bottom_model=guest_bottom,
            interactive_layer=interactive_layer
        )
        model.set_context(ctx)
        model.double()
        optimizer = t.optim.Adam(model.parameters(), lr=0.01)

        # trainer = HeteroNNTrainerGuest(ctx, model, optimizer, dataset, None, loss_fn, batch_size=batch_size,
        #                                epochs=epoch)
        # trainer.train()

        args = TrainingArguments(
            num_train_epochs=5,
            per_device_train_batch_size=16,
            disable_tqdm=False
        )
        trainer = HeteroNNTrainerGuest(
            ctx=ctx,
            model=model,
            optimizer=optimizer,
            train_set=dataset,
            loss_fn=loss_fn,
            training_args=args,
        )
        trainer.train()

        pred = model.predict(X_g)
        # compute auc
        from sklearn.metrics import roc_auc_score
        print(roc_auc_score(y.detach().numpy(), pred.detach().numpy()))

    elif party == "host":

        ctx = create_ctx(host, get_current_datetime_str())

        df = pd.read_csv('/home/cwj/FATE/FATE-2.0/FATE/examples/data/breast_hetero_host.csv')
        X_h = t.Tensor(df.drop(columns=['id']).values).type(t.float64)[0: sample_num]

        dataset = TensorDataset(X_h)

        layer = InteractiveLayerHost()
        model = HeteroNNModelHost(host_bottom, interactive_layer=layer)
        model.double()
        optimizer = t.optim.Adam(model.parameters(), lr=0.01)

        args = TrainingArguments(
            num_train_epochs=5,
            per_device_train_batch_size=16,
            disable_tqdm=False
        )
        trainer = HeteroNNTrainerHost(
            ctx=ctx,
            model=model,
            optimizer=optimizer,
            train_set=dataset,
            training_args=args
        )
        trainer.train()
        # trainer = HeteroNNTrainerHost(ctx, model, optimizer, dataset, None, batch_size=batch_size, epochs=epoch)
        # trainer.train()

        pred = model.predict(X_h)