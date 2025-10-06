# Ollama Network Sharing Guide

**Purpose:** Share Ollama AI capabilities across your local network so other users (Mac, Windows, etc.) can access your Linux Ollama installation without installing anything locally.

## **Setup Instructions**

### **1. Configure Ollama for Network Access**
```bash
# Set Ollama to listen on all network interfaces
export OLLAMA_HOST172.17.0.1:11434

# Make it permanent by adding to ~/.bashrc
echo 'export OLLAMA_HOST=0.0.0.0:11434' >> ~/.bashrc
source ~/.bashrc

# Restart Ollama service
ollama serve
```

### **2. Find Your Linux Machine's IP Address**
```bash
# Get your IP address
ip addr show | grep "inet " | grep -v 127.0.0.1
# Or
hostname -I
```

### **3. Configure Security (Optional)**
```bash
# Restrict access to your local network only
export OLLAMA_HOST=192.168.1.0/24:11434

# Or use firewall rules
sudo ufw allow from 192.168.1.0/24 to any port 11434
```

## **How Mac Users Can Access**

### **Option 1: Simple Web Interface (Recommended for Non-Technical Users)**

#### **Setup Open WebUI (Best for Non-Technical Users):**
```bash
# Install Docker if you don't have it
sudo apt update
sudo apt install docker.io
sudo systemctl start docker
sudo usermod -aG docker $USER

# Install Open WebUI with network access
docker run -d -p 0.0.0.0:3000:8080 -v ollama:/root/.ollama -e OLLAMA_BASE_URL=http://host.docker.internal:11434 --name open-webui ghcr.io/open-webui/open-webui:main
```

#### **For Non-Technical Users:**
- **URL:** `http://YOUR_LINUX_IP:3000`
- **Looks like ChatGPT** - familiar, user-friendly interface
- **No technical setup** required on Mac
- **Works on any device** - Mac, iPhone, iPad
- **Simple account creation** (username/password)
- **Chat history** and model selection

#### **Even Simpler (No Account Required):**
```bash
# Start without authentication for instant access
docker run -d -p 0.0.0.0:3000:8080 -v ollama:/root/.ollama -e OLLAMA_BASE_URL=http://host.docker.internal:11434 -e WEBUI_AUTH=False --name open-webui ghcr.io/open-webui/open-webui:main
```

### **Option 2: Basic Web Interface:**
- **URL:** `http://YOUR_LINUX_IP:11434`
- **Simple chat interface** for general AI questions
- **No installation needed** on Mac

### **Mac Apps That Connect to Ollama:**
- **Ollama Desktop** - Official desktop app
- **Open WebUI** - Advanced web interface
- **MacGPT** - Can connect to local Ollama servers
- **Cursor** - Can use Ollama as backend
- **Raycast** - Quick AI commands

### **API Integration:**
```bash
# Mac users can make API calls
curl http://YOUR_LINUX_IP:11434/api/generate \
  -d '{"model": "llama2:7b", "prompt": "Hello, how are you?"}'
```

## **Use Cases for Mac Users**

### **Code Assistance:**
- Code completion and debugging help
- Code review and optimization suggestions
- Documentation generation

### **Writing and Content:**
- Email drafting and professional writing
- Content creation and editing
- Translation and language help

### **Research and Analysis:**
- Data analysis help
- Research paper summarization
- Academic writing assistance

### **Creative Tasks:**
- Creative writing and brainstorming
- Idea generation and problem solving
- Learning and educational content

## **Performance Considerations**

### **Your Linux Machine:**
- CPU usage will increase with multiple users
- RAM usage scales with concurrent requests
- Network bandwidth for model responses

### **Recommended Settings:**
```bash
# Limit concurrent requests
export OLLAMA_NUM_PARALLEL=2

# Set memory limits
export OLLAMA_MAX_LOADED_MODELS=1
```

## **Security Notes**

### **Network Security:**
- **No authentication** by default (Ollama is open)
- **Consider VPN** for remote access
- **Monitor usage** if needed
- **Restrict to local network** for security

### **Access Control:**
- Ollama is open by default - anyone on your network can use it
- Consider firewall rules to restrict access
- Monitor usage if you have bandwidth concerns

## **Benefits for Mac Users**

### **✅ Advantages:**
- **No installation** required on Mac
- **Access to powerful AI** without local resources
- **Shared models** - everyone uses the same AI
- **Centralized management** - you control the AI system

### **⚠️ Limitations:**
- **Requires network connection** to your Linux machine
- **Performance depends** on your Linux machine's specs
- **Limited when Linux machine is offline**

## **Quick Setup for Mac Users**

### **For Technical Users:**
1. **Find your Linux IP:** `hostname -I`
2. **Configure Ollama:** `export OLLAMA_HOST=0.0.0.0:11434`
3. **Tell Mac users:** "Connect to `http://YOUR_IP:11434`"
4. **They can start chatting** immediately!

### **For Non-Technical Users (Recommended):**
1. **Install Open WebUI** (see Option 1 above)
2. **Find your Linux IP:** `hostname -I`
3. **Give them simple instructions:**
   ```
   "Open any web browser and go to: http://YOUR_IP:3000
   Create a simple account (username/password)
   Start chatting - it's like ChatGPT but running on your computer!"
   ```
4. **They get a ChatGPT-like experience** with zero technical setup!

## **Troubleshooting**

### **Common Issues:**
- **Connection refused:** Check if Ollama is running and listening on the right port
- **Slow responses:** Multiple users will slow down the system
- **Model not found:** Make sure models are downloaded on the Linux machine

### **Testing:**
```bash
# Test from Linux machine
curl http://localhost:11434/api/generate -d '{"model": "llama2:7b", "prompt": "Hello"}'

# Test from Mac (replace YOUR_IP)
curl http://YOUR_IP:11434/api/generate -d '{"model": "llama2:7b", "prompt": "Hello"}'
```

---

**Note:** This setup turns your Linux machine into an "AI server" for your network. All users share the same models and processing power, so performance will depend on your Linux machine's capabilities and the number of concurrent users.
