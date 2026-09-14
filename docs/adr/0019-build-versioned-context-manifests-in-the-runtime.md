# Build versioned context manifests in the Runtime

The Agent Runtime assembles every model-visible context from versioned policy, workflow instructions, the currently exposed tool specifications, trusted user state, explicitly marked untrusted evidence, and bounded session context. Compaction may summarize conversation, but authoritative facts and evidence are reloaded from their sources; every model call records a context manifest sufficient to explain and reproduce what the model could see.
