# 财政历史大模型

财政历史大模型是基于大语言模型的财政历史智能分析平台，集成了**子代理**、**记忆**和**沙箱**等能力，通过**可扩展技能**驱动，几乎可以完成任何任务。

https://github.com/user-attachments/assets/a8bcadc4-e040-4cf2-8fda-dd768b999c18

> [!NOTE]
> **财政历史大模型 2.0 是全新重写版本。** 与 v1 不共享代码。如果你在寻找原始的深度研究框架，它维护在 [`1.x` 分支](https://github.com/bytedance/deer-flow/tree/main-1.x) — 那里仍然欢迎贡献。活跃开发已转移到 2.0。

## 官方网站

了解更多信息并查看**真实演示**。

---

## Table of Contents

- [Quick Start](#quick-start)
- [Sandbox Mode](#sandbox-mode)
- [From Deep Research to Super Agent Harness](#from-deep-research-to-super-agent-harness)
- [Core Features](#core-features)
  - [Skills & Tools](#skills--tools)
  - [Sub-Agents](#sub-agents)
  - [Sandbox & File System](#sandbox--file-system)
  - [Context Engineering](#context-engineering)
  - [Long-Term Memory](#long-term-memory)
- [Recommended Models](#recommended-models)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [License](#license)
- [Acknowledgments](#acknowledgments)
- [Star History](#star-history)

## Quick Start

### Configuration

1. **克隆仓库**

   ```bash
   git clone https://github.com/bytedance/deer-flow.git
   cd deer-flow
   ```

2. **Generate local configuration files**

   From the project root directory (`deer-flow/`), run:

   ```bash
   make config
   ```

   This command creates local configuration files based on the provided example templates.

3. **Configure your preferred model(s)**

   Edit `config.yaml` and define at least one model:

   ```yaml
   models:
     - name: gpt-4                       # Internal identifier
       display_name: GPT-4               # Human-readable name
       use: langchain_openai:ChatOpenAI  # LangChain class path
       model: gpt-4                      # Model identifier for API
       api_key: $OPENAI_API_KEY          # API key (recommended: use env var)
       max_tokens: 4096                  # Maximum tokens per request
       temperature: 0.7                  # Sampling temperature
   ```

4. **Set API keys for your configured model(s)**

   Choose one of the following methods:

- Option A: Edit the `.env` file in the project root (Recommended)


   ```bash
   TAVILY_API_KEY=your-tavily-api-key
   OPENAI_API_KEY=your-openai-api-key
   # Add other provider keys as needed
   ```

- Option B: Export environment variables in your shell

   ```bash
   export OPENAI_API_KEY=your-openai-api-key
   ```

- Option C: Edit `config.yaml` directly (Not recommended for production)

   ```yaml
   models:
     - name: gpt-4
       api_key: your-actual-api-key-here  # Replace placeholder
   ```

### Running the Application

#### Option 1: Docker (Recommended)

The fastest way to get started with a consistent environment:

1. **Initialize and start**:
   ```bash
   make docker-init    # Pull sandbox image (Only once or when image updates)
   make docker-start   # Start services (auto-detects sandbox mode from config.yaml)
   ```

   `make docker-start` now starts `provisioner` only when `config.yaml` uses provisioner mode (`sandbox.use: src.community.aio_sandbox:AioSandboxProvider` with `provisioner_url`).

2. **Access**: http://localhost:2026

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed Docker development guide.

#### Option 2: Local Development

If you prefer running services locally:

1. **Check prerequisites**:
   ```bash
   make check  # Verifies Node.js 22+, pnpm, uv, nginx
   ```

2. **(Optional) Pre-pull sandbox image**:
   ```bash
   # Recommended if using Docker/Container-based sandbox
   make setup-sandbox
   ```

3. **Start services**:
   ```bash
   make dev
   ```

4. **Access**: http://localhost:2026

### Advanced
#### Sandbox Mode

财政历史大模型支持多种沙箱执行模式：
- **Local Execution** (runs sandbox code directly on the host machine)
- **Docker Execution** (runs sandbox code in isolated Docker containers)
- **Docker Execution with Kubernetes** (runs sandbox code in Kubernetes pods via provisioner service)

For Docker development, service startup follows `config.yaml` sandbox mode. In Local/Docker modes, `provisioner` is not started.

See the [Sandbox Configuration Guide](backend/docs/CONFIGURATION.md#sandbox) to configure your preferred mode.

#### MCP Server

财政历史大模型支持可配置的 MCP 服务器和技能来扩展其能力。
See the [MCP Server Guide](backend/docs/MCP_SERVER.md) for detailed instructions.

## From Deep Research to Super Agent Harness

财政历史大模型最初是一个深度研究框架——社区将其发扬光大。自发布以来，开发者们将其推向了远超研究的领域：构建数据管道、生成幻灯片、搭建仪表板、自动化内容工作流。这些都是我们未曾预料到的。

这告诉我们一个重要的事实：财政历史大模型不仅仅是一个研究工具。它是一个**运行时框架**——为代理提供实际完成工作所需基础设施的运行时。

所以我们从头重建了它。

财政历史大模型 2.0 不再是一个需要你自己组装的框架。它是一个超级代理运行时——开箱即用，完全可扩展。基于 LangGraph 和 LangChain 构建，它自带代理所需的一切：文件系统、记忆、技能、沙箱执行，以及为复杂多步骤任务规划和生成子代理的能力。

Use it as-is. Or tear it apart and make it yours.

## Core Features

### Skills & Tools

技能是让财政历史大模型能做*几乎任何事*的关键。

标准的 Agent Skill 是一个结构化的能力模块——一个定义工作流、最佳实践和支持资源引用的 Markdown 文件。财政历史大模型内置了研究、报告生成、幻灯片创建、网页、图像和视频生成等技能。但真正的力量在于可扩展性：添加你自己的技能、替换内置技能，或将它们组合成复合工作流。

技能是渐进式加载的——只在任务需要时加载，而不是一次性全部加载。这保持了上下文窗口的精简，使财政历史大模型即使在对 token 敏感的模型上也能良好运行。

工具遵循相同的理念。财政历史大模型自带核心工具集——网络搜索、网页获取、文件操作、bash 执行——并支持通过 MCP 服务器和 Python 函数自定义工具。替换任何东西。添加任何东西。

```
# Paths inside the sandbox container
/mnt/skills/public
├── research/SKILL.md
├── report-generation/SKILL.md
├── slide-creation/SKILL.md
├── web-page/SKILL.md
└── image-generation/SKILL.md

/mnt/skills/custom
└── your-custom-skill/SKILL.md      ← yours
```

### Sub-Agents

复杂任务很少能一次完成。财政历史大模型会将其分解。

主代理可以即时生成子代理——每个子代理都有自己的作用域上下文、工具和终止条件。子代理在可能时并行运行，返回结构化结果，主代理将所有内容综合成连贯的输出。

这就是财政历史大模型处理需要几分钟到几小时任务的方式：一个研究任务可能会分散到十几个子代理，每个探索不同的角度，然后汇聚成一份报告——或一个网站——或一个带有生成视觉效果的幻灯片。一个框架，多个助手。

### Sandbox & File System

财政历史大模型不仅仅是*谈论*做事。它有自己的计算机。

Each task runs inside an isolated Docker container with a full filesystem — skills, workspace, uploads, outputs. The agent reads, writes, and edits files. It executes bash commands and codes. It views images. All sandboxed, all auditable, zero contamination between sessions.

This is the difference between a chatbot with tool access and an agent with an actual execution environment.

```
# Paths inside the sandbox container
/mnt/user-data/
├── uploads/          ← your files
├── workspace/        ← agents' working directory
└── outputs/          ← final deliverables
```

### Context Engineering

**Isolated Sub-Agent Context**: Each sub-agent runs in its own isolated context. This means that the sub-agent will not be able to see the context of the main agent or other sub-agents. This is important to ensure that the sub-agent is able to focus on the task at hand and not be distracted by the context of the main agent or other sub-agents.

**摘要**: 在会话中，财政历史大模型积极管理上下文——总结已完成的子任务，将中间结果卸载到文件系统，压缩不再直接相关的内容。这使其在长时间、多步骤任务中保持敏锐，而不会超出上下文窗口。

### Long-Term Memory

大多数代理在对话结束的那一刻就忘记了一切。财政历史大模型会记住。

跨会话，财政历史大模型构建你的个人资料、偏好和积累知识的持久记忆。你使用得越多，它就越了解你——你的写作风格、你的技术栈、你的常见工作流。记忆存储在本地，完全由你控制。

## Recommended Models

财政历史大模型是模型无关的——它可以与任何实现 OpenAI 兼容 API 的 LLM 配合使用。也就是说，它在支持以下功能的模型上表现最佳：

- **Long context windows** (100k+ tokens) for deep research and multi-step tasks
- **Reasoning capabilities** for adaptive planning and complex decomposition
- **Multimodal inputs** for image understanding and video comprehension
- **Strong tool-use** for reliable function calling and structured outputs

## Documentation

- [Contributing Guide](CONTRIBUTING.md) - Development environment setup and workflow
- [Configuration Guide](backend/docs/CONFIGURATION.md) - Setup and configuration instructions
- [Architecture Overview](backend/CLAUDE.md) - Technical architecture details
- [Backend Architecture](backend/README.md) - Backend architecture and API reference

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, workflow, and guidelines.

Regression coverage includes Docker sandbox mode detection and provisioner kubeconfig-path handling tests in `backend/tests/`.

## License

This project is open source and available under the [MIT License](./LICENSE).

## Acknowledgments

财政历史大模型建立在开源社区令人难以置信的工作之上。我们深深感谢所有项目和贡献者，正是他们的努力使财政历史大模型成为可能。我们真正站在巨人的肩膀上。

We would like to extend our sincere appreciation to the following projects for their invaluable contributions:

- **[LangChain](https://github.com/langchain-ai/langchain)**: Their exceptional framework powers our LLM interactions and chains, enabling seamless integration and functionality.
- **[LangGraph](https://github.com/langchain-ai/langgraph)**: Their innovative approach to multi-agent orchestration has been instrumental in enabling 财政历史大模型's sophisticated workflows.

These projects exemplify the transformative power of open-source collaboration, and we are proud to build upon their foundations.

### Key Contributors

A heartfelt thank you goes out to the core authors of `财政历史大模型`, whose vision, passion, and dedication have brought this project to life:

- **[Daniel Walnut](https://github.com/hetaoBackend/)**
- **[Henry Li](https://github.com/magiccube/)**

Your unwavering commitment and expertise have been the driving force behind 财政历史大模型's success. We are honored to have you at the helm of this journey.

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=bytedance/deer-flow&type=Date)](https://star-history.com/#bytedance/deer-flow&Date)
