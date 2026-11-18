
text = open("corpus.txt", encoding="utf-8").read()
chars = sorted(set(text))
print(len(text), len(chars))

stoi = {ch: i for i, ch in enumerate(chars)}   # dict: character -> integer
itos = {i: ch for i, ch in enumerate(chars)}

def encode(s):
    return [stoi[ch] for ch in s]

def decode(ids):
    return ''.join(itos[i] for i in ids)

import torch

data = torch.tensor(encode(text), dtype=torch.long)

print(data.shape)
print(data[:100])
print(decode(data[:100].tolist()))

n = int(0.9 * len(data))

train_data = data[:n]
val_data = data[n:]
block_size = 128
batch_size = 32

def get_batch(split):
    d = train_data if split == "train" else val_data

    ix = torch.randint(len(d) - block_size, (batch_size,))

    x = torch.stack([
        d[i:i + block_size] for i in ix
    ])

    y = torch.stack([
        d[i + 1:i + block_size + 1] for i in ix
    ])

    return x, y
x, y = get_batch("train")
print(x.shape, y.shape)
print((x[0][1:] == y[0][:-1]).all())
print("Vocabulary:", len(chars))
print("Dataset size:", data.numel())
print("Tensor memory:", data.element_size() * data.numel() / 1024**2, "MB")