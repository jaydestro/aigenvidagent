"""A real Microsoft Agent Framework executor graph, without model inference."""

from typing import Never

from agent_framework import WorkflowBuilder, WorkflowContext, executor


async def execute_graph(payload, gate, stage, render, verify):
    @executor(id="approval_gate")
    async def approval_gate(
        message: dict, context: WorkflowContext[dict]
    ) -> None:
        await context.send_message(gate(message))

    @executor(id="stage_sources")
    async def stage_sources(
        message: dict, context: WorkflowContext[dict]
    ) -> None:
        await context.send_message(stage(message))

    @executor(id="render_variants")
    async def render_variants(
        message: dict, context: WorkflowContext[dict]
    ) -> None:
        await context.send_message(render(message))

    @executor(id="verify_outputs")
    async def verify_outputs(
        message: dict, context: WorkflowContext[Never, dict]
    ) -> None:
        await context.yield_output(verify(message))

    builder = WorkflowBuilder(
        start_executor=approval_gate, output_from=[verify_outputs]
    )
    builder.add_edge(approval_gate, stage_sources).add_edge(
        stage_sources, render_variants
    ).add_edge(render_variants, verify_outputs)
    result = await builder.build().run(payload)
    outputs = result.get_outputs()
    if not outputs:
        raise RuntimeError("Workflow did not produce a verified result")
    return outputs[0]
