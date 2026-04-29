export const SUGGESTIONS: string[] = [
  "Retrieval-Augmented Generation for scientific papers",
  "Vision transformers in medical imaging",
  "Diffusion models for image synthesis",
  "Large language model alignment techniques",
  "Graph neural networks for drug discovery",
  "Federated learning privacy guarantees",
  "Reinforcement learning from human feedback",
  "Neural architecture search methods",
  "Contrastive learning in self-supervised vision",
  "Mixture of experts language models",
  "Protein structure prediction with deep learning",
  "Multimodal models combining text and vision",
  "Chain-of-thought prompting in LLMs",
  "Efficient transformers and attention approximations",
  "Autonomous driving with imitation learning",
  "Quantum computing algorithms for optimization",
  "Zero-shot learning in natural language processing",
  "Anomaly detection in time series with deep learning",
  "Causal inference in machine learning",
  "Speech synthesis and voice cloning with neural networks",
];


export function pickSuggestions(n: number): string[] {
  const shuffled = [...SUGGESTIONS].sort(() => Math.random() - 0.5);
  return shuffled.slice(0, n);
}
