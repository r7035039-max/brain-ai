import torch
import torch.nn as nn
import torch.nn.functional as F

# Load text
with open("corpus.txt", "r", encoding="utf-8") as f:
    text = f.read()

# Create vocabulary
chars = sorted(list(set(text)))
vocab_size = len(chars)

stoi = {ch: i for i, ch in enumerate(chars)}
itos = {i: ch for i, ch in enumerate(chars)}

# Encode text
data = torch.tensor(
    [stoi[ch] for ch in text],
    dtype=torch.long
)

# Split dataset
n = int(0.9 * len(data))
train_data = data[:n]
val_data = data[n:]

print("Characters:", len(text))
print("Vocabulary:", vocab_size)
print("Training data:", len(train_data))
block_size = 32
batch_size = 64

def get_batch(split):
    d = train_data if split == "train" else val_data

    ix = torch.randint(
        len(d) - block_size - 1,
        (batch_size,)
    )

    x = torch.stack([d[i:i + block_size] for i in ix])
    y = torch.stack([d[i + block_size] for i in ix])

    return x, y


x, y = get_batch("train")

print("Input shape:", x.shape)
print("Target shape:", y.shape)
class MLP(nn.Module):
    def __init__(self):
        super().__init__()

        self.embedding = nn.Embedding(vocab_size, 32)

        self.fc1 = nn.Linear(32 * block_size, 256)

        self.fc2 = nn.Linear(256, vocab_size)

    def forward(self, x):
        emb = self.embedding(x)

        emb = emb.reshape(x.shape[0], -1)

        hidden = F.relu(self.fc1(emb))

        logits = self.fc2(hidden)

        return logits


model = MLP()

logits = model(x)

print("Logits shape:", logits.shape)

print("Parameters:", sum(p.numel() for p in model.parameters()))
optimizer = torch.optim.AdamW(model.parameters(), lr=0.001)

for step in range(1001):

    x, y = get_batch("train")

    logits = model(x)

    loss = F.cross_entropy(logits, y)

    optimizer.zero_grad()
    loss.backward()
    optimizer.step()

    if step % 100 == 0:
        print(f"Step {step}: loss = {loss.item():.4f}")
def generate(start_text, max_new_chars=300):
    model.eval()

    context = torch.tensor(
        [stoi[ch] for ch in start_text],
        dtype=torch.long
    )

    for _ in range(max_new_chars):
        x = context[-block_size:]

        # Pad short input to 32 characters
        if len(x) < block_size:
            padding = torch.zeros(
                block_size - len(x),
                dtype=torch.long
            )
            x = torch.cat((padding, x))

        x = x.unsqueeze(0)

        with torch.no_grad():
            logits = model(x)

        probabilities = F.softmax(logits, dim=-1)
        next_char = torch.multinomial(probabilities, 1)

        context = torch.cat((context, next_char[0]))

    model.train()

    return ''.join(itos[i.item()] for i in context)
model.eval()

with torch.no_grad():
    x, y = get_batch("val")
    logits = model(x)
    val_loss = F.cross_entropy(logits, y)

print("Validation loss:", val_loss.item())

model.train()
print(generate("Привет", 500))