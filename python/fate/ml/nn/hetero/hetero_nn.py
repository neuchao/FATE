import torch
from torch import nn
from typing import Any, Dict, List, Union, Callable
from fate.arch import Context
from torch.utils.data import Dataset
from transformers import PreTrainedTokenizer
from transformers import EvalPrediction
from transformers.trainer_callback import TrainerCallback
from typing import Optional
from fate.ml.nn.model_zoo.hetero_nn_model import HeteroNNModelGuest, HeteroNNModelHost
from fate.ml.nn.trainer.trainer_base import HeteroTrainerBase, TrainingArguments


class HeteroNNTrainerGuest(HeteroTrainerBase):

    def __init__(
            self,
            ctx: Context,
            model: HeteroNNModelGuest,
            training_args: TrainingArguments,
            train_set: Dataset,
            val_set: Dataset = None,
            loss_fn: nn.Module = None,
            optimizer = None,
            data_collator: Callable = None,
            scheduler = None,
            tokenizer: Optional[PreTrainedTokenizer] = None,
            callbacks: Optional[List[TrainerCallback]] = [],
            compute_metrics: Optional[Callable[[EvalPrediction], Dict]] = None,
    ):

        assert isinstance(model, HeteroNNModelGuest), ('Model should be a HeteroNNModelGuest instance, '
                                                       'but got {}.').format(type(model))

        super().__init__(
            ctx=ctx,
            model=model,
            training_args=training_args,
            train_set=train_set,
            val_set=val_set,
            loss_fn=loss_fn,
            optimizer=optimizer,
            data_collator=data_collator,
            scheduler=scheduler,
            tokenizer=tokenizer,
            callbacks=callbacks,
            compute_metrics=compute_metrics
        )

    def compute_loss(self, model, inputs, **kwargs):
        # (features, labels), this format is used in FATE-1.x
        if isinstance(inputs, tuple) or isinstance(inputs, list):
            if len(inputs) == 2:  # data & label
                feats, labels = inputs
                output = model(feats)
                loss = self.loss_func(output, labels)
                return loss
            if len(inputs) == 1: # label only
                labels = inputs[0]
                output = model()
                loss = self.loss_func(output, labels)
                return loss
        else:
            # unknown format, go to super class function
            return super().compute_loss(model, inputs, **kwargs)

    def training_step(self, model: Union[HeteroNNModelGuest, HeteroNNModelHost],
                      inputs: Dict[str, Union[torch.Tensor, Any]]) -> torch.Tensor:
        # override the training_step method in Trainer
        model.train()
        inputs = self._prepare_inputs(inputs)

        with self.compute_loss_context_manager():
            loss = self.compute_loss(model, inputs)

        if self.args.n_gpu > 1:
            loss = loss.mean()  # mean() to average on multi-gpu parallel training

        model.backward(loss)

        return loss.detach() / self.args.gradient_accumulation_steps


class HeteroNNTrainerHost(HeteroTrainerBase):

    def __init__(
            self,
            ctx: Context,
            model: HeteroNNModelHost,
            training_args: TrainingArguments,
            train_set: Dataset,
            val_set: Dataset = None,
            optimizer=None,
            data_collator: Callable = None,
            scheduler=None,
            tokenizer: Optional[PreTrainedTokenizer] = None,
            callbacks: Optional[List[TrainerCallback]] = [],
            compute_metrics: Optional[Callable[[EvalPrediction], Dict]] = None,
    ):
        assert isinstance(model, HeteroNNModelHost), ('Model should be a HeteroNNModelHost instance, '
                                                       'but got {}.').format(type(model))

        super().__init__(
            ctx=ctx,
            model=model,
            training_args=training_args,
            train_set=train_set,
            val_set=val_set,
            loss_fn=None,
            optimizer=optimizer,
            data_collator=data_collator,
            scheduler=scheduler,
            tokenizer=tokenizer,
            callbacks=callbacks,
            compute_metrics=compute_metrics
        )
    def compute_loss(self, model, inputs, **kwargs):
        # host side not computing loss
        if isinstance(inputs, tuple) or isinstance(inputs, list):
            feats = inputs[0]
            model(feats)
            return 0
        else:
            return super().compute_loss(model, inputs, **kwargs)

    def training_step(self, model: Union[HeteroNNModelGuest, HeteroNNModelHost],
                      inputs: Dict[str, Union[torch.Tensor, Any]]) -> torch.Tensor:
        # override the training_step method in Trainer
        model.train()
        inputs = self._prepare_inputs(inputs)
        with self.compute_loss_context_manager():
            self.compute_loss(model, inputs)
        model.backward()
        # host has no label, will never have loss
        return torch.tensor(0)
