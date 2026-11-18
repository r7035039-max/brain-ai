import csv, json, os, random, re, shutil, time, torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import LoraConfig, get_peft_model, PeftModel

MODEL = "Qwen/Qwen3-0.6B"
MAX_LEN, BATCH, LR = 256, 8, 2e-4
PILOT_STEPS = None        # e.g. 20 for a test run, None = full epoch
SAVE_EVERY = 100          # use 10 for the resume test
KEEP = 2                  # how many checkpoints to keep
WARMUP = 20
CKPT_DIR = "ckpt"
TEST_PROMPTS = ["привет, как дела?", "что делаешь?", "го гулять?"]
torch.set_num_threads(6)

os.makedirs(CKPT_DIR, exist_ok=True)

# ---------- helpers ----------
def latest_ckpt():
    best = None
    for name in os.listdir(CKPT_DIR):
        m = re.fullmatch(r"step_(\d+)", name)
        path = os.path.join(CKPT_DIR, name)
        if m and os.path.exists(os.path.join(path, "state.pt")):
            n = int(m.group(1))
            if best is None or n > best[0]:
                best = (n, path)
    return best  # (step, path) or None

def lr_at(step, total):
    warm = min(1.0, (step + 1) / WARMUP)
    decay = max(0.05, 1 - step / total)
    return LR * warm * decay

# ---------- model ----------
tok = AutoTokenizer.from_pretrained(MODEL)
base = AutoModelForCausalLM.from_pretrained(MODEL, torch_dtype=torch.float32)

# remove half-written checkpoints from a crash
for name in os.listdir(CKPT_DIR):
    if name.startswith("tmp_"):
        shutil.rmtree(os.path.join(CKPT_DIR, name), ignore_errors=True)

resume = latest_ckpt()
if resume:
    start, path = resume
    model = PeftModel.from_pretrained(base, path, is_trainable=True)
    print(f"RESUMING from step {start} ({path})", flush=True)
else:
    start = 0
    model = get_peft_model(base, LoraConfig(
        r=16, lora_alpha=32, lora_dropout=0.05, task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"]))
model.print_trainable_parameters()

params = [p for p in model.parameters() if p.requires_grad]
opt = torch.optim.AdamW(params, lr=LR)
if resume:
    state = torch.load(os.path.join(path, "state.pt"), weights_only=False)
    opt.load_state_dict(state["opt"])
    assert state["step"] == start

# ---------- data ----------
def encode(sample):
    msgs = sample["messages"]
    prompt = tok.apply_chat_template(
        msgs[:-1], tokenize=False,
        add_generation_prompt=True, enable_thinking=False)
    p = tok(prompt, add_special_tokens=False)["input_ids"]
    r = tok(msgs[-1]["content"] + "<|im_end|>",
            add_special_tokens=False)["input_ids"]
    ids = (p + r)[-MAX_LEN:]
    labels = ([-100] * len(p) + r)[-MAX_LEN:]
    return ids, labels

def collate(batch):
    enc = [encode(s) for s in batch]
    n = max(len(i) for i, _ in enc)
    pad = tok.pad_token_id
    ids = torch.tensor([i + [pad] * (n - len(i)) for i, _ in enc])
    lab = torch.tensor([l + [-100] * (n - len(l)) for _, l in enc])
    mask = torch.tensor([[1] * len(i) + [0] * (n - len(i)) for i, _ in enc])
    return ids, lab, mask

data = [json.loads(l) for l in open("train.jsonl", encoding="utf-8")]
random.seed(0)                 # same shuffle every run -> resume is exact
random.shuffle(data)

steps_per_epoch = len(data) // BATCH
total = PILOT_STEPS or steps_per_epoch

# ---------- save / sample ----------
def save_ckpt(done):
    tmp = os.path.join(CKPT_DIR, f"tmp_{done}")
    final = os.path.join(CKPT_DIR, f"step_{done}")
    shutil.rmtree(tmp, ignore_errors=True)
    model.save_pretrained(tmp)
    torch.save({"opt": opt.state_dict(), "step": done},
               os.path.join(tmp, "state.pt"))
    shutil.rmtree(final, ignore_errors=True)
    os.rename(tmp, final)      # rename only after everything is written
    # delete old checkpoints
    steps = sorted(int(m.group(1)) for n in os.listdir(CKPT_DIR)
                   if (m := re.fullmatch(r"step_(\d+)", n)))
    for s in steps[:-KEEP]:
        shutil.rmtree(os.path.join(CKPT_DIR, f"step_{s}"), ignore_errors=True)

def sample(done):
    model.eval()
    lines = [f"=== step {done} ==="]
    for q in TEST_PROMPTS:
        text = tok.apply_chat_template(
            [{"role": "user", "content": q}], tokenize=False,
            add_generation_prompt=True, enable_thinking=False)
        x = tok(text, return_tensors="pt", add_special_tokens=False)
        with torch.no_grad():
            out = model.generate(**x, max_new_tokens=50, do_sample=True,
                                 temperature=0.8, top_p=0.9)
        a = tok.decode(out[0][x["input_ids"].shape[1]:],
                       skip_special_tokens=True)
        lines.append(f"> {q}\n{a}")
    model.train()
    with open("samples.txt", "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n\n")

# ---------- train ----------
if start >= total:
    print("Already finished.")
    raise SystemExit

model.train()
log_new = not os.path.exists("log.csv")
log = open("log.csv", "a", newline="", encoding="utf-8")
w = csv.writer(log)
if log_new:
    w.writerow(["step", "loss", "lr", "sec"])

t0, tokens = time.time(), 0
for step in range(start, total):
    ts = time.time()
    lr = lr_at(step, total)
    for g in opt.param_groups:
        g["lr"] = lr

    ids, lab, mask = collate(data[step * BATCH:(step + 1) * BATCH])
    loss = model(input_ids=ids, attention_mask=mask, labels=lab).loss
    loss.backward()
    torch.nn.utils.clip_grad_norm_(params, 1.0)
    opt.step()
    opt.zero_grad()

    tokens += int(mask.sum())
    w.writerow([step, f"{loss.item():.4f}", f"{lr:.2e}", f"{time.time()-ts:.1f}"])
    log.flush()
    if step % 10 == 0:
        print(f"step {step}/{total} loss {loss.item():.3f}", flush=True)

    done = step + 1
    if done % SAVE_EVERY == 0 or done == total:
        save_ckpt(done)
        sample(done)

dt = time.time() - t0
print(f"{tokens/dt:.1f} tok/s, {dt/(total-start):.1f} s/step")
model.save_pretrained("lora_final")
print("DONE")