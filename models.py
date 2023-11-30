import torch
import torchvision.models as models
import torch.nn as nn
import torch.optim as optim
from tqdm import tqdm
from utils import StatCollector, calculate_sparsity
from pruner import Pruner
from quantizer import Quantizer

class ModelLoader:
    @staticmethod
    def load_model(model_name):
        if model_name.lower() == 'alexnet':
            model = models.alexnet(weights=None)
            model.classifier[6] = nn.Linear(4096, 10)
        elif model_name.lower() == 'vgg16':
            model = models.vgg16(weights=None)
        else:
            raise ValueError("Unsupported model. Please choose 'AlexNet' or 'VGG16'.")
        return model

class ModelTrainer:
    def __init__(self, model, trainloader, testloader, stat_collector, learning_rate=3e-3,session_name='default'):
        self.model = model
        self.session_name = session_name
        self.trainloader = trainloader
        self.testloader = testloader
        self.criterion = nn.CrossEntropyLoss()
        self.optimizer = optim.AdamW(self.model.parameters(), lr=learning_rate)
        self.stat_collector = stat_collector
        self.device = torch.device('mps:0') if torch.backends.mps.is_available() else 'cpu'
        self.model.to(self.device)
        self.pruner = Pruner(pruning_threshold=1e-4)
        self.quantizer = Quantizer(self.model)
    
    def quantize_model(self):
        #self.quantizer.load_index_matrices(folder=f'models/{self.session_name})
        self.quantizer.quantize_weights(folder=f'models/{self.session_name}')
        torch.save(self.model.state_dict(), f"models/{self.session_name}/quantized_{0}.pth")

    def evaluate(self):
        self.model.eval()
        correct = 0
        total = 0
        with torch.no_grad():
            for data in tqdm(self.testloader, total=len(self.testloader), desc='Evaluating'):
                images, labels = data
                images = images.to(self.device)
                labels = labels.to(self.device)
                outputs = self.model(images)
                _, predicted = torch.max(outputs.data, 1)
                total += labels.size(0)
                correct += (predicted == labels).sum().item()
        accuracy = correct / total
        return accuracy

    def train_baseline(self, epochs):
        for epoch in range(epochs):
            self.model.train()
            running_loss = 0.0
            pbar = tqdm(enumerate(self.trainloader), total=len(self.trainloader),desc=f"Epoch {epoch + 1}/{epochs}")
            for i, data in pbar:
                inputs, labels = data
                inputs = inputs.to(self.device)
                labels = labels.to(self.device)

                self.optimizer.zero_grad()
                outputs = self.model(inputs)

                loss = self.criterion(outputs, labels)
                loss.backward()
                self.optimizer.step()
                running_loss += loss.item()

                if self.stat_collector:
                    self.stat_collector.log_loss(loss.item())
                    if i % 10 == 0:
                        self.stat_collector.plot_stats(interval=10, prefix='baseline')
        
            # Evaluate after each epoch
            accuracy = self.evaluate()
            if self.stat_collector:
                self.stat_collector.log_accuracy(accuracy)
            print(f"Baseline: Epoch {epoch + 1}/{epochs}, Loss: {running_loss / len(self.trainloader)}, Accuracy: {100 * accuracy:.2f}%")
            # save the model
            torch.save(self.model.state_dict(), f"models/{self.session_name}/baseline_{epoch + 1}.pth")
        self.stat_collector.clear_stats()

    def train_and_prune(self, stages, epochs):
        for stage in range(stages):
            for epoch in range(epochs):
                self.model.train()
                running_loss = 0.0
                pbar = tqdm(enumerate(self.trainloader), total=len(self.trainloader),desc=f"Epoch {epoch + 1}/{epochs}")
                for i, data in pbar:
                    inputs, labels = data
                    inputs = inputs.to(self.device)
                    labels = labels.to(self.device)

                    self.optimizer.zero_grad()
                    outputs = self.model(inputs)

                    loss = self.criterion(outputs, labels)
                    loss.backward()
                    self.optimizer.step()
                    running_loss += loss.item()

                    if self.stat_collector:
                        self.stat_collector.log_loss(loss.item())
                        if i % 10 == 0:
                            self.stat_collector.plot_stats(interval=10, prefix='prune')
                    

                # Evaluate after each epoch
                accuracy = self.evaluate()
                if self.stat_collector:
                    self.stat_collector.log_accuracy(accuracy)
                pbar.set_description(f"Pruning: Epoch {epoch + 1}/{epochs}, Loss: {running_loss / len(self.trainloader)}, Accuracy: {100 * accuracy:.2f}%")
            
            self.model = self.pruner.prune_network(self.model)
            sparsity = calculate_sparsity(self.model)
            pbar.set_description(f"Sparsity after stage {stage + 1}: {sparsity:.6%}")
            self.stat_collector.log_sparsity(sparsity)
            self.stat_collector.plot_stats(interval=10,prefix='prune')

            # save the model:
            torch.save(self.model.state_dict(), f"models/{self.session_name}/prune_{stage + 1}.pth")
        self.stat_collector.clear_stats()
    def train_and_quantize(self, epochs=10):
        self.quantize_model()
        for epoch in range(epochs):
            self.model.train()
            running_loss = 0.0
            pbar = tqdm(enumerate(self.trainloader), total=len(self.trainloader),desc=f"Epoch {epoch + 1}/{epochs}")
            for i, data in pbar:
                
                
                ############################################################################################################
                def check_unique_values_in_conv2d():
                    unique_values_count = {}
                    for name, module in self.model.named_modules():
                        if isinstance(module, torch.nn.Conv2d):
                            unique_values = torch.unique(module.weight.data)
                            unique_values_count[name] = [len(unique_values)]
                        # also check the sum
                        if isinstance(module, torch.nn.Conv2d):
                            unique_values_count[name].append(torch.sum(module.weight.data))
                    return unique_values_count
                '''' Check the unique values of each layer's weight tensor '''
                unique_values_count = check_unique_values_in_conv2d()
                if i % 10 == 0:
                    for layer_name, count in unique_values_count.items():
                        print(f"{layer_name} has {count[0]} unique values")
                        print(f"{layer_name} has sum of {count[1]}")
                        if count == 3:
                            print(f"--> {layer_name} satisfies the 3 unique values condition")
                        else:
                            print(f"--> {layer_name} does not satisfy the 3  unique values condition")
                ############################################################################################################
            

                inputs, labels = data
                inputs = inputs.to(self.device)
                labels = labels.to(self.device)

                self.optimizer.zero_grad()
                outputs = self.model(inputs)

                loss = self.criterion(outputs, labels)
                loss.backward()

                # Quantize the gradients
                self.quantizer.update_gradients()
                self.optimizer.step()


                running_loss += loss.item()

                if self.stat_collector:
                    self.stat_collector.log_loss(loss.item())
                    if i % 10 == 0:
                        self.stat_collector.plot_stats(interval=10, prefix='quantize')
            
            
            # Evaluate after each epoch
            accuracy = self.evaluate()
            if self.stat_collector:
                self.stat_collector.log_accuracy(accuracy)
            pbar.set_description(f"Quantization: Epoch {epoch + 1}/{epochs}, Loss: {running_loss / len(self.trainloader)}, Accuracy: {100 * accuracy:.2f}%")
            
            # save the model
            torch.save(self.model.state_dict(), f"models/{self.session_name}/quantized_{epoch + 1}.pth")
        self.stat_collector.clear_stats()    

