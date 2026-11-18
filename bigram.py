import torch
import torch.nn as nn
import torch.nn.functional as F
from tokenizer import chars, get_batch, decode, stoi


vocab_size = len(chars)

# Our trainable parameter matrix
W = nn.Parameter(torch.zeros(vocab_size, vocab_size))

print(W.shape)
print("Parameters:", W.numel())

def forward(x):
    logits = W[x]
    return logits

x, y = get_batch("train")

logits = forward(x)

loss = F.cross_entropy(
    logits.reshape(-1, vocab_size),
    y.reshape(-1)
)

print("Loss:", loss.item())

optimizer = torch.optim.Adam([W], lr=0.01)

for step in range(501):

    x, y = get_batch("train")

    logits = forward(x)

    loss = F.cross_entropy(
        logits.reshape(-1, vocab_size),
        y.reshape(-1)
    )

    optimizer.zero_grad()

    loss.backward()

    optimizer.step()

    if step % 100 == 0:
        print(step, loss.item())

@torch.no_grad()
def estimate_loss():
    results = {}

    for split in ["train", "val"]:
        losses = torch.zeros(20)

        for k in range(20):
            x, y = get_batch(split)
            logits = forward(x)

            losses[k] = F.cross_entropy(
                logits.reshape(-1, vocab_size),
                y.reshape(-1)
            )

        results[split] = losses.mean().item()

    return results


print(estimate_loss())
optimizer = torch.optim.Adam([W], lr=0.01)

for step in range(501):

    x, y = get_batch("train")

    logits = forward(x)

    loss = F.cross_entropy(
        logits.reshape(-1, vocab_size),
        y.reshape(-1)
    )

    optimizer.zero_grad()
    loss.backward()
    optimizer.step()

    if step % 100 == 0:
        print(step, loss.item())

@torch.no_grad()
def generate(start, max_new_tokens=300):
    idx = torch.tensor(
        [stoi[c] for c in start],
        dtype=torch.long
    )

    for _ in range(max_new_tokens):
        logits = W[idx[-1]]
        probs = F.softmax(logits, dim=-1)

        next_id = torch.multinomial(probs, num_samples=1)

        idx = torch.cat((idx, next_id))

    return decode(idx.tolist())


print(generate("<me>", 300))