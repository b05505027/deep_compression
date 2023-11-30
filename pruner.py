import torch
import torch.nn.utils.prune as prune

class Pruner:
    def __init__(self, pruning_threshold=1e-4):
        self.pruning_threshold = pruning_threshold

    def prune_network(self, model):
        for name, module in model.named_modules():
            if isinstance(module, torch.nn.Conv2d) or isinstance(module, torch.nn.Linear):
                prune.custom_from_mask(module, name='weight', mask=self.create_pruning_mask(module.weight))
        return model

    def create_pruning_mask(self, weight_tensor):
        mean = weight_tensor.abs().mean()
        std = weight_tensor.abs().std()
        mask = weight_tensor.abs() > mean - std
        return mask
