import torch
import torch.nn as nn
import torch.nn.functional as F

from torch.utils.data import DataLoader, random_split
from torch.utils.tensorboard import SummaryWriter
from tqdm import tqdm
import kornia

from dataset import SyntheticDataset

device = torch.device("cuda:1" if torch.cuda.is_available() else "cpu")

BATCH_SIZE = 64
LR = 1e-5

DATA_PATH = "/home/thomas/Data/train2017"


class Flatten(nn.Module):
    def forward(self, x):
        return x.view(x.size(0), -1)


class Block(nn.Module):
    def __init__(self, inchannels, outchannels, batch_norm=True):
        super(Block, self).__init__()
        layers = []
        layers.append(nn.Conv2d(inchannels, outchannels, kernel_size=3, padding=1))
        layers.append(nn.ReLU())
        if batch_norm:
            layers.append(nn.BatchNorm2d(outchannels))
        layers.append(nn.Conv2d(outchannels, outchannels, kernel_size=3, padding=1))
        layers.append(nn.ReLU())
        if batch_norm:
            layers.append(nn.BatchNorm2d(outchannels))
        layers.append(nn.MaxPool2d(2, 2))
        self.layers = nn.Sequential(*layers)

    def forward(self, x):
        return self.layers(x)


class Net(nn.Module):
    def __init__(self, batch_norm=True):
        super(Net, self).__init__()
        self.cnn = nn.Sequential(
            Block(2, 64, batch_norm),
            Block(64, 128, batch_norm),
            Block(128, 256, batch_norm),
            Block(256, 256, batch_norm),
            Block(256, 256, batch_norm),
            Flatten(),
        )
        self.fc = nn.Sequential(
            nn.Linear(256 * 4 * 4, 4096), nn.ReLU(), nn.Linear(4096, 4 * 2),
        )

    def forward(self, a, b):
        x = torch.cat((a, b), dim=1)  # combine two images in channel dimension
        x = self.cnn(x)
        x = self.fc(x)
        delta = x.view(-1, 4, 2)
        return delta


def photometric_loss(delta, img_a, img_b, points):
    points_hat = points + delta
    h = kornia.get_perspective_transform(points, points_hat)
    img_b_hat = kornia.warp_perspective(img_a, h, (256, 256))
    return torch.mean(torch.abs(img_b_hat - img_b))


def train_step(model, optimizer, dataloader, writer):
    model.train()
    total_loss = 0.0
    size = len(dataloader.dataset)
    for img_a, img_b, patch_a, patch_b, points in tqdm(dataloader, leave=False):
        img_a, img_b, patch_a, patch_b, points = (
            img_a.to(device),
            img_b.to(device),
            patch_a.to(device),
            patch_b.to(device),
            points.to(device),
        )
        delta = model(patch_a, patch_b)
        loss = photometric_loss(delta, img_a, img_b, points)
        total_loss += loss.item() * img_a.size(0)
        loss.backward()
        optimizer.step()
        writer.add_scalar("train_loss", loss.item())
        writer.flush()
    return total_loss / size


def valid_step(model, dataloader):
    model.eval()
    with torch.no_grad():
        total_loss = 0.0
        size = len(dataloader.dataset)
        for img_a, img_b, patch_a, patch_b, points in tqdm(dataloader, leave=False):
            img_a, img_b, patch_a, patch_b, points = (
                img_a.to(device),
                img_b.to(device),
                patch_a.to(device),
                patch_b.to(device),
                points.to(device),
            )
            delta = model(patch_a, patch_b)
            loss = photometric_loss(delta, img_a, img_b, points)
            total_loss += loss.item() * img_a.size(0)
        return total_loss / size


def fit(epochs):
    dataset = SyntheticDataset(DATA_PATH)
    train_size = int(0.8 * len(dataset))
    train_set, valid_set = random_split(
        dataset, [train_size, len(dataset) - train_size]
    )
    train_loader = DataLoader(
        train_set, batch_size=BATCH_SIZE, shuffle=True, num_workers=4
    )
    valid_loader = DataLoader(valid_set, batch_size=BATCH_SIZE, num_workers=4)

    writer = SummaryWriter()
    model = Net().to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=LR)

    for e in range(epochs):
        train_loss = train_step(model, optimizer, train_loader, writer)
        valid_loss = valid_step(model, valid_loader)
        print(f"{e}\t{train_loss:.4f}\t{valid_loss:.4f}")
        torch.save(model.state_dict(), f"model_{e}.pt")


def test_dataset():
    dataset = SyntheticDataset(DATA_PATH)

    img_a, img_b, patch_a, patch_b, points = dataset[0]
    print(img_a.shape)
    print(patch_a.shape)
    print(patch_b.shape)
    print(points.shape)

    import matplotlib.pyplot as plt
    from torchvision import transforms

    to_pil = transforms.ToPILImage()

    for img in [img_a, patch_a, patch_b]:
        plt.imshow(to_pil(img), cmap="gray")
        plt.show()


# test_dataset()
fit(20)