# OLLAMA Capabilities and Learning Resources

## What is OLLAMA?

OLLAMA is a tool that runs large language models (LLMs) locally on your machine. It's like having ChatGPT, but:
- **Private** - Your data stays on your machine
- **Free** - No API costs or usage limits
- **Offline** - Works without internet (after initial model download)
- **Customizable** - Run different models for different tasks

## What Can OLLAMA Do?

### 1. **Text Generation & Chat**
- Natural conversations (like ChatGPT)
- Creative writing
- Storytelling
- Role-playing scenarios

**Example:**
```bash
curl http://localhost:11434/api/generate -d '{
  "model": "llama2:7b",
  "prompt": "Write a short story about a robot learning to paint",
  "stream": false
}'
```

### 2. **Code Generation & Assistance**
- Write code in multiple languages
- Debug and explain code
- Refactor and optimize
- Generate documentation

**Models for coding:**
- `codellama:7b` - Specialized for code
- `deepseek-coder:6.7b` - Advanced code generation
- `mistral:7b` - General purpose, good at code

**Example:**
```bash
ollama run codellama:7b "Write a Python function to sort a list of dictionaries by a key"
```

### 3. **Text Analysis & Summarization**
- Summarize long documents
- Extract key points
- Analyze sentiment
- Extract structured data (like your paper metadata extraction!)

**Your current use case:**
- Extracting metadata from academic papers
- Parsing structured information from unstructured text
- Validating extracted data

### 4. **Translation**
- Translate between languages
- Preserve context and nuance
- Handle technical terminology

**Example:**
```bash
ollama run llama2:7b "Translate this to Norwegian: 'The quick brown fox jumps over the lazy dog'"
```

### 5. **Question Answering**
- Answer questions based on knowledge
- Explain complex concepts
- Provide step-by-step instructions

### 6. **Creative Tasks**
- Poetry and creative writing
- Brainstorming ideas
- Generating content ideas
- Writing emails, letters, etc.

### 7. **Data Extraction & Formatting**
- Extract structured data from text
- Convert between formats (JSON, CSV, etc.)
- Parse and reformat documents

**Example (what you're already doing):**
```python
# Extract metadata from paper text
metadata = ollama_client.extract_paper_metadata(text)
# Returns structured JSON with title, authors, DOI, etc.
```

## GPU Memory Considerations (4GB T1000)

Your NVIDIA T1000 has **4GB VRAM**, which limits which models you can run efficiently. Here's what you need to know:

### Model Memory Requirements

- **7B models (quantized)**: ~4-5GB VRAM (fits with some optimization)
- **13B models**: ~8-10GB VRAM (too large for 4GB GPU)
- **Smaller models (3B-7B)**: Best fit for 4GB GPU

### Optimization Tips for 4GB GPU

1. **Use quantized models** (Q4_0, Q5_0) - smaller, faster
2. **Limit context length** - shorter conversations use less memory
3. **Unload models when not in use** - free GPU memory
4. **Use CPU offloading** - OLLAMA automatically offloads to CPU when GPU is full
5. **Run one model at a time** - don't load multiple models simultaneously

### What Works Well on 4GB GPU

✅ **7B models (quantized)**: llama2:7b, mistral:7b, codellama:7b
✅ **Smaller models**: phi-2:2.7b, tinyllama:1.1b (very fast)
⚠️ **13B+ models**: Will work but may be slow (CPU offloading)

## Available Models

### General Purpose Models (Recommended for 4GB GPU)

**llama2:7b** (You have this) ✅
- Good balance of quality and speed
- General purpose conversations
- ~4GB download, ~4-5GB VRAM usage
- **Works well on 4GB GPU** (with some CPU offloading)
- Good for: Chat, writing, general tasks

**mistral:7b** (Recommended to try) ✅
- Often better than llama2 for many tasks
- Good reasoning capabilities
- ~4GB download, ~4-5GB VRAM usage
- **Works well on 4GB GPU** (with some CPU offloading)
- Good for: Complex reasoning, analysis

**phi-2:2.7b** (Fast, efficient) ✅✅
- Small but capable model
- Very fast inference
- ~1.6GB download, ~2-3GB VRAM usage
- **Excellent for 4GB GPU** - plenty of headroom
- Good for: Quick tasks, simple queries, fast responses
- **Quick tasks examples**: Simple Q&A, text formatting, basic translations, short summaries, simple code snippets, quick explanations

**tinyllama:1.1b** (Ultra-fast) ✅✅
- Very small model
- Extremely fast
- ~637MB download, ~1-2GB VRAM usage
- **Perfect for 4GB GPU** - minimal memory usage
- Good for: Simple tasks, quick responses, testing
- **Quick tasks examples**: Very simple questions, basic text processing, format conversion, quick lookups, testing prompts

**llama2:13b** (Not recommended for 4GB GPU) ❌
- More capable than 7b version
- Better at complex tasks
- ~7GB download, ~8-10GB VRAM usage
- **Too large for 4GB GPU** - will be very slow (mostly CPU)
- Consider only if you really need the extra capability

### Code-Specific Models (Recommended for 4GB GPU)

**codellama:7b** (You have this) ✅
- Specialized for programming
- Understands many languages
- ~4GB download, ~4-5GB VRAM usage
- **Works well on 4GB GPU** (with some CPU offloading)
- Good for: Code generation, debugging, explanations

**deepseek-coder:6.7b** ✅
- Advanced code generation
- Better at complex programming tasks
- ~4GB download, ~4-5GB VRAM usage
- **Works well on 4GB GPU** (with some CPU offloading)
- Slightly smaller than codellama, may be slightly faster

### Specialized Models (Recommended for 4GB GPU)

**llama2-uncensored:7b** ✅
- Less filtered responses
- For research/creative work
- ~4GB download, ~4-5GB VRAM usage
- **Works well on 4GB GPU**

**neural-chat:7b** ✅
- Optimized for conversations
- Better at following instructions
- ~4GB download, ~4-5GB VRAM usage
- **Works well on 4GB GPU**

**phi-2:2.7b** ✅✅
- Small but capable
- Fast inference
- Good for quick tasks
- ~1.6GB download, ~2-3GB VRAM usage
- **Excellent for 4GB GPU** - very efficient

## Understanding "Quick Tasks" vs "Complex Tasks"

### Quick Tasks (Use phi-2:2.7b or tinyllama:1.1b)
**Characteristics:**
- Simple, straightforward requests
- Short responses expected
- Don't require deep reasoning
- Fast turnaround needed
- Low memory usage preferred

**Examples:**
- "What is machine learning?" (simple explanation)
- "Translate 'hello' to Norwegian" (basic translation)
- "Format this text as a list" (text formatting)
- "Write a Python function to add two numbers" (simple code)
- "Summarize this in one sentence: [short text]" (brief summary)
- "What does this acronym mean?" (lookup/definition)
- "Convert this date format" (simple conversion)
- "Generate a short email subject line" (quick generation)

**Why use smaller models:**
- ⚡ Much faster (seconds vs minutes)
- 💾 Less GPU memory (leaves room for other tasks)
- ✅ Quality is usually sufficient for simple tasks
- 🔄 Can handle many requests quickly

### Complex Tasks (Use llama2:7b or mistral:7b)
**Characteristics:**
- Require deep understanding or reasoning
- Long, detailed responses needed
- Multi-step thinking required
- Context-heavy analysis
- Quality is more important than speed

**Examples:**
- "Analyze this research paper and explain the methodology" (complex analysis)
- "Write a comprehensive guide to Docker containers" (detailed content)
- "Debug this complex Python code with multiple issues" (deep code analysis)
- "Compare these three research approaches and recommend one" (reasoning)
- "Extract structured metadata from this academic paper" (your current use case!)
- "Explain quantum computing with examples and analogies" (detailed explanation)
- "Generate a research proposal outline" (complex structured output)

**Why use larger models:**
- 🧠 Better reasoning and understanding
- 📝 Higher quality, more nuanced responses
- 🔍 Better at complex extraction and analysis
- 💡 Can handle multi-step tasks
- ⚠️ Slower but worth it for quality

## Use Cases in Your Research Workflow

### 1. **Paper Metadata Extraction** (Current)
- Extract structured metadata from PDFs
- Validate extracted information
- Handle multilingual documents

### 2. **Paper Summarization**
- Summarize long papers
- Extract key findings
- Generate abstracts

### 3. **Literature Review Assistance**
- Compare multiple papers
- Identify common themes
- Generate synthesis

### 4. **Writing Assistance**
- Draft research notes
- Improve writing clarity
- Generate outlines

### 5. **Code Documentation**
- Generate code comments
- Create API documentation
- Explain complex algorithms

## Learning Resources

### Official Documentation

1. **OLLAMA Official Website**
   - URL: https://ollama.ai/
   - Official documentation, model library, examples

2. **OLLAMA GitHub**
   - URL: https://github.com/ollama/ollama
   - Source code, issues, community discussions
   - Model library: https://ollama.ai/library

3. **OLLAMA API Documentation**
   - URL: https://github.com/ollama/ollama/blob/main/docs/api.md
   - Complete API reference
   - Examples for all endpoints

### Tutorials and Guides

4. **OLLAMA Tutorials (YouTube)**
   - Search: "OLLAMA tutorial" or "OLLAMA setup"
   - Many step-by-step video guides

5. **Medium Articles**
   - Search: "OLLAMA local LLM"
   - Practical use cases and examples

6. **Reddit Community**
   - r/LocalLLaMA - Active community
   - r/OLLAMA - OLLAMA-specific discussions
   - Great for troubleshooting and tips

### Model-Specific Resources

7. **Hugging Face**
   - URL: https://huggingface.co/
   - Model cards, documentation
   - Many models available (though OLLAMA has its own format)

8. **Model Cards on OLLAMA Library**
   - Each model has documentation
   - Examples and use cases
   - Performance benchmarks

### Advanced Topics

9. **Prompt Engineering**
   - Learn how to write effective prompts
   - Search: "LLM prompt engineering guide"
   - Better prompts = better results

10. **Fine-tuning (Advanced)**
    - Customize models for your specific needs
    - Requires more technical knowledge
    - OLLAMA supports model importing

### Practical Examples

11. **OLLAMA Examples Repository**
    - Check GitHub for example scripts
    - Community-contributed use cases

12. **Your Own Codebase**
    - Look at `shared_tools/ai/ollama_client.py`
    - See how metadata extraction is implemented
    - Adapt patterns for other tasks

## Getting Started with New Models

### Pull a New Model

```bash
# Pull a model (downloads to container)
docker exec ollama-gpu ollama pull mistral:7b

# Or from host if OLLAMA_HOST is set
export OLLAMA_HOST=http://localhost:11434
ollama pull mistral:7b
```

### Test a Model

```bash
# Via CLI
ollama run mistral:7b "Explain quantum computing in simple terms"

# Via API
curl http://localhost:11434/api/generate -d '{
  "model": "mistral:7b",
  "prompt": "Explain quantum computing in simple terms",
  "stream": false
}'

# Via WebUI
# Just select the model from the dropdown in the interface
```

## Advanced Features

### 1. **Streaming Responses**
Get responses as they're generated (faster perceived response):

```python
import requests

response = requests.post(
    'http://localhost:11434/api/generate',
    json={
        'model': 'llama2:7b',
        'prompt': 'Write a story',
        'stream': True  # Enable streaming
    },
    stream=True
)

for line in response.iter_lines():
    if line:
        print(line.decode('utf-8'))
```

### 2. **System Prompts**
Set behavior/context for the model:

```python
response = requests.post(
    'http://localhost:11434/api/generate',
    json={
        'model': 'llama2:7b',
        'prompt': 'What is the weather?',
        'system': 'You are a helpful assistant that always responds in Norwegian.'
    }
)
```

### 3. **Context Management**
Maintain conversation context:

```python
# Keep conversation history
messages = [
    {'role': 'user', 'content': 'Hello'},
    {'role': 'assistant', 'content': 'Hi! How can I help?'},
    {'role': 'user', 'content': 'What did I just say?'}
]

response = requests.post(
    'http://localhost:11434/api/chat',
    json={
        'model': 'llama2:7b',
        'messages': messages
    }
)
```

### 4. **Model Management**
List, copy, delete models:

```bash
# List models
ollama list

# Show model info
ollama show llama2:7b

# Copy a model
ollama cp llama2:7b my-custom-name

# Delete a model (frees space)
ollama rm old-model-name
```

## Best Practices for 4GB GPU

### 1. **Choose the Right Model**
- **Small/quick tasks**: Use phi-2:2.7b or tinyllama:1.1b (fast, efficient)
- **General tasks**: Use 7b models (llama2:7b, mistral:7b) - best balance
- **Code tasks**: Use codellama:7b or deepseek-coder:6.7b
- **Avoid 13b+ models**: Too large for 4GB GPU, will be very slow

### 2. **Monitor GPU Memory**
```bash
# Check GPU usage
nvidia-smi

# Watch in real-time
watch -n 1 nvidia-smi
```

### 3. **Optimize Memory Usage**
- **Unload unused models**: `ollama rm model-name` (frees GPU memory)
- **Limit context**: Shorter conversations = less memory
- **One model at a time**: Don't load multiple models simultaneously
- **Use quantized models**: Q4_0 quantization is optimal for 4GB

### 4. **Optimize Prompts**
- Be specific about what you want
- Provide context and examples
- Use clear instructions
- **Keep prompts shorter** on 4GB GPU to reduce memory usage

### 5. **Manage Resources (Critical for 4GB GPU)**
- **Monitor GPU/RAM usage**: `nvidia-smi` regularly
- **Don't load too many models at once**: One at a time is best
- **Use model unloading when done**: `ollama rm` to free memory
- **Restart container if memory gets fragmented**: `docker restart ollama-gpu`
- **Use smaller models for quick tasks**: phi-2:2.7b instead of llama2:7b when possible

### 6. **Error Handling**
- Always validate responses
- Handle timeouts gracefully
- Check model availability before use
- **Watch for out-of-memory errors**: May need to use smaller model or restart

## Integration Ideas for Your Project

### 1. **Enhanced Paper Processing**
- Summarize papers before processing
- Extract key concepts automatically
- Generate tags based on content

### 2. **Smart File Naming**
- Generate better filenames based on content
- Suggest improvements to extracted metadata

### 3. **Documentation Generation**
- Auto-generate README files
- Create API documentation
- Write code comments

### 4. **Research Assistance**
- Answer questions about your papers
- Find connections between papers
- Generate research questions

## Troubleshooting (4GB GPU Specific)

### Model Not Found
```bash
# Pull the model first
docker exec ollama-gpu ollama pull model-name
```

### Out of Memory (Common with 4GB GPU)
**Symptoms**: Slow responses, errors, or model fails to load

**Solutions**:
1. **Use smaller models**: Switch to phi-2:2.7b or tinyllama:1.1b
2. **Unload other models**: `docker exec ollama-gpu ollama rm unused-model`
3. **Restart container**: `docker restart ollama-gpu` (clears fragmented memory)
4. **Reduce context length**: Shorter conversations use less memory
5. **Check GPU memory**: `nvidia-smi` to see actual usage
6. **Use CPU offloading**: OLLAMA will automatically use CPU when GPU is full (slower but works)

### Slow Responses (4GB GPU)
**Possible causes**:
- **GPU memory full**: Model partially on CPU (much slower)
  - Solution: Use smaller model or restart container
- **Large model**: 7b models may be slow on 4GB GPU
  - Solution: Try phi-2:2.7b for faster responses
- **Long context**: Very long conversations slow down
  - Solution: Start new conversation or reduce context

**Check GPU utilization**:
```bash
# See if GPU is being used
nvidia-smi

# If GPU memory is full, you'll see CPU usage instead
# This means model is running on CPU (slow)
```

### Model Loading Issues
If a 7b model won't load:
- **Try smaller model first**: phi-2:2.7b to verify GPU works
- **Check Docker GPU access**: `docker exec ollama-gpu nvidia-smi`
- **Restart container**: Sometimes fixes memory issues

## Next Steps (Optimized for 4GB GPU)

1. **Try Different Models (Start Small)**
   - **First**: Pull `phi-2:2.7b` - fast, efficient, great for 4GB GPU
   - **Then**: Compare `mistral:7b` vs `llama2:7b` (both work but may use CPU offloading)
   - **For code**: Test `codellama:7b` (works well on 4GB)
   - **Avoid**: 13b+ models (too large for your GPU)

2. **Monitor GPU Performance**
   - Run `nvidia-smi` while using models
   - See which models fit best in 4GB
   - Identify when CPU offloading happens (slower)

3. **Experiment with Prompts**
   - Try different prompt styles
   - Test system prompts
   - Experiment with few-shot examples
   - **Keep prompts shorter** to reduce memory usage

4. **Build Custom Tools**
   - Create scripts for specific tasks
   - Integrate with your workflow
   - Automate repetitive tasks
   - **Use smaller models** for quick/automated tasks

5. **Join the Community**
   - Reddit: r/LocalLLaMA, r/OLLAMA
   - GitHub discussions
   - Share your use cases
   - **Ask about 4GB GPU optimization** - others have similar setups

## Summary (4GB T1000 GPU)

OLLAMA is a powerful tool for:
- ✅ Local, private AI processing
- ✅ No API costs or limits
- ✅ Customizable for your needs
- ✅ Works offline
- ✅ Integrates with your existing tools

### Best Models for Your 4GB GPU:
- **Fast & Efficient**: phi-2:2.7b, tinyllama:1.1b
- **Best Balance**: llama2:7b, mistral:7b, codellama:7b (may use some CPU offloading)
- **Avoid**: 13b+ models (too large, will be very slow)

### Key Tips:
- Monitor GPU memory with `nvidia-smi`
- Use smaller models for quick tasks
- Restart container if memory gets fragmented
- One model at a time works best

Start with **phi-2:2.7b** for fast, efficient responses, then try 7b models for more complex tasks. Experiment and find what works best for your workflow!

