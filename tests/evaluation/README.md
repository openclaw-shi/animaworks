# AnimaWorks Memory Performance Evaluation Framework

This directory contains the implementation of the memory performance evaluation framework for AnimaWorks, as specified in:
`docs/research/memory-performance-evaluation-protocol.md`

## Overview

The framework provides a comprehensive system for evaluating the performance of AnimaWorks' memory system across four experimental conditions:

- **Condition A**: BM25 search only (baseline)
- **Condition B**: Vector search only
- **Condition C**: Hybrid search (BM25 + Vector + Recency)
- **Condition D**: Hybrid search + Priming layer

## Directory Structure

```
tests/evaluation/
├── framework/              # Core framework implementation
│   ├── __init__.py
│   ├── config.py           # Experiment configuration data models
│   ├── framework.py        # Main experiment orchestration
│   ├── metrics.py          # Metrics collection tools
│   └── logger.py           # Experiment logging
├── datasets/               # Memory base datasets
│   ├── business/           # Business assistant domain
│   ├── tech_support/       # Technical support domain
│   └── education/          # Education coach domain
├── scenarios/              # Conversation scenarios (YAML)
├── ground_truth/           # Ground truth annotations
├── results/                # Experiment results
│   ├── raw/                # Raw experiment logs
│   ├── processed/          # Processed data
│   └── figures/            # Generated graphs
├── scripts/                # Execution scripts
├── test_framework.py       # Unit tests
└── README.md               # This file
```

## Phase 1 Implementation (Current)

Phase 1 provides the core infrastructure:

### 1. Configuration (`config.py`)

Data models for experimental setup:

```python
from framework import ExperimentConfig, MemorySize, ConversationLength

# Create Condition D (Hybrid + Priming) configuration
config = ExperimentConfig.create_condition_d(
    experiment_id="exp_001",
    participants=30,
    memory_size=MemorySize.MEDIUM,
    conversation_length=ConversationLength.MEDIUM,
    domain=Domain.BUSINESS,
    priming_budget=2000
)
```

**Key classes**:
- `ExperimentConfig`: Main experiment configuration with validation
- `SearchConfig`: Search method configuration (BM25/Vector/Hybrid)
- `TurnMetrics`: Per-turn metrics (latency, precision, recall, tokens)
- `ConversationMetrics`: Aggregated conversation-level metrics

### 2. Metrics Collection (`metrics.py`)

Tools for measuring performance:

```python
from framework import MetricsCollector

collector = MetricsCollector()

# Measure latency
result, latency_ms = await collector.measure_latency_async(some_async_func, arg1, arg2)

# Calculate search quality
precision, recall, f1 = collector.calculate_precision_recall(
    retrieved=["doc1", "doc2", "doc3"],
    relevant=["doc1", "doc3", "doc4"],
    k=3
)

# Count tokens
tokens = collector.count_tokens(text)

# Calculate statistics
percentiles = collector.calculate_percentiles(latencies, [50, 95, 99])
summary = collector.calculate_summary_stats(values)
```

**Key features**:
- High-precision latency measurement (`time.perf_counter()`)
- Precision@k, Recall@k, F1@k calculation
- Mean Average Precision (MAP)
- Normalized Discounted Cumulative Gain (NDCG@k)
- Token counting (heuristic-based, replaceable with actual tokenizer)
- Statistical aggregations (percentiles, summary stats)

### 3. Experiment Logging (`logger.py`)

Structured logging to JSON:

```python
from framework import ExperimentLogger

logger = ExperimentLogger(
    experiment_id="exp_001",
    output_dir=Path("results/raw"),
    condition="D",
    participant_id=1
)

# Log conversation
logger.start_conversation("conv_001")

# Log turn metrics
logger.log_turn_metrics(turn_metrics)

# Log component-specific metrics
logger.log_priming(turn_id="turn_001", latency_ms=50.0, tokens=100)
logger.log_search(turn_id="turn_001", latency_ms=80.0, precision=0.8, recall=0.7, f1=0.75, retrieved_count=3)

# End conversation
logger.end_conversation(conv_metrics)

# Generate summary
summary = logger.generate_summary()
```

**Output structure**:
```
results/raw/{experiment_id}/
├── metadata.json           # Experiment configuration
├── conversations/          # Per-conversation metrics
│   ├── conv_001.json
│   └── ...
├── turns/                  # Per-turn metrics
│   ├── turn_001.json
│   └── ...
├── priming.jsonl           # Priming-specific logs
├── search.jsonl            # Search-specific logs
├── errors.jsonl            # Error logs
└── summary.json            # Aggregated summary
```

### 4. Experiment Framework (`framework.py`)

Main orchestration:

```python
from framework import MemoryExperiment, Scenario, Turn, ScenarioType

# Create experiment
config = ExperimentConfig.create_condition_d(experiment_id="exp_001")
experiment = MemoryExperiment(config, output_dir=Path("results/raw"))

# Load scenarios
scenarios = [
    Scenario(
        scenario_id="fact_001",
        scenario_type=ScenarioType.FACTUAL_RECALL,
        domain="business",
        turns=[
            Turn(
                turn_id="turn_001",
                message="山田さんのプロジェクトの締め切りはいつでしたか?",
                relevant_memories=["knowledge/clients/yamada-project.md"],
                expected_answer="2026年3月15日"
            )
        ]
    )
]
experiment.scenarios = scenarios

# Run experiment
results = await experiment.run_all()
```

**Key features**:
- Automatic agent creation and initialization
- Scenario execution with metric collection
- Priming measurement (Condition D only)
- Search quality evaluation (Precision@k, Recall@k)
- Comprehensive error handling and logging

## Usage

### Running Unit Tests

```bash
cd /home/main/dev/animaworks-memory-eval
pytest tests/evaluation/test_framework.py -v
```

### Example: Running a Single Participant

```python
import asyncio
from pathlib import Path
from framework import ExperimentConfig, MemoryExperiment

async def main():
    # Configure experiment
    config = ExperimentConfig.create_condition_d(
        experiment_id="pilot_001",
        participants=5,  # Start with pilot
    )

    # Create experiment
    experiment = MemoryExperiment(
        config=config,
        output_dir=Path("results/raw")
    )

    # Load scenarios (TODO: implement load_scenarios)
    # experiment.load_scenarios(Path("scenarios/"))

    # Validate setup
    if not experiment.validate_setup():
        print("Setup validation failed")
        return

    # Run single participant
    summary = await experiment.run_participant(participant_id=1)
    print(f"Participant 1 complete: {summary}")

asyncio.run(main())
```

## Integration with AnimaWorks

The framework is designed to integrate with AnimaWorks core components:

### Agent Creation (TODO)

```python
from core.person import DigitalPerson

async def create_agent(self, participant_id: int) -> DigitalPerson:
    person_dir = self._create_person_environment(participant_id)
    agent = DigitalPerson(
        person_dir=person_dir,
        search_config=self.config.search_config
    )
    return agent
```

### Priming Measurement (TODO)

```python
async def _measure_priming(self, agent: DigitalPerson, message: str):
    result, latency = await self.metrics_collector.measure_latency_async(
        agent.priming_engine.prime_memories,
        message=message,
        sender="user"
    )
    return result, latency
```

### Response Measurement (TODO)

```python
async def _measure_response(self, agent: DigitalPerson, message: str):
    result, latency = await self.metrics_collector.measure_latency_async(
        agent.process_message,
        message=message
    )
    # Extract metrics from result
    response = AgentResponse(...)
    return response, latency
```

## Next Steps (Phase 2+)

Phase 2 and beyond will add:

1. **Dataset Generation** (`dataset_generator.py`)
   - Memory base generation (knowledge, episodes, skills)
   - Scenario generation (factual, episodic, multihop, long)
   - Domain-specific templates

2. **Ground Truth Management** (`ground_truth.py`)
   - Annotation interface
   - Inter-annotator agreement (Cohen's κ)
   - Ground truth validation

3. **Statistical Analysis** (`analysis.py`)
   - Hypothesis testing (t-test, ANOVA, logistic regression)
   - Effect size calculation
   - Power analysis

4. **Visualization** (`visualization.py`)
   - Latency distribution plots
   - Precision/Recall curves
   - Comparison charts across conditions

5. **Execution Scripts**
   - `run_experiment.py`: Run full experiments
   - `run_analysis.py`: Statistical analysis
   - `generate_paper_figures.py`: Publication-quality figures

## Evaluation Metrics

The framework measures:

### Speed Metrics
- **Priming Latency**: Time for priming layer (Condition D)
- **Search Latency**: Time for memory search
- **Response Latency**: End-to-end response time
- **Percentiles**: P50, P95, P99

### Precision Metrics
- **Precision@k**: Fraction of retrieved documents that are relevant
- **Recall@k**: Fraction of relevant documents that are retrieved
- **F1@k**: Harmonic mean of Precision and Recall
- **MAP**: Mean Average Precision
- **NDCG@k**: Normalized Discounted Cumulative Gain

### Efficiency Metrics
- **Token Consumption**: Total tokens in context
- **Tool Call Count**: Number of search_memory calls
- **Priming Tokens**: Tokens injected by priming layer

### Quality Metrics (Future)
- **Dialog Quality Score**: Human evaluation (1-5 scale)
- **Memory Retention Rate**: Long-term recall success
- **Consistency Score**: Memory coherence across conversations

## Design Principles

1. **Measurement Accuracy**: Use `time.perf_counter()` for high-precision timing
2. **Type Safety**: Full type hints (`str | None` format)
3. **Validation**: Comprehensive input validation in dataclasses
4. **Logging**: Structured JSON logging for reproducibility
5. **Modularity**: Clear separation of concerns (config, metrics, logging, orchestration)
6. **Testability**: Unit tests for all components
7. **Documentation**: Google-style docstrings throughout

## Dependencies

- Python 3.12+
- `numpy`: Statistical calculations
- `pytest`: Unit testing
- `pydantic` or `dataclasses`: Data validation
- AnimaWorks core (for integration)

## References

See `docs/research/memory-performance-evaluation-protocol.md` for:
- Detailed research background
- Hypothesis statements
- Complete evaluation protocol
- Statistical analysis plan
- Expected outcomes
