"""Pure, deterministic graph assembly. Every id, pointer and variable is produced here."""

from __future__ import annotations

import copy
import uuid

from ..model import Catalog, Provenance, Step, Workflow, rewrite_variables
from .extract import Intent, NodeIntent


def assemble(
    intent: Intent, catalog: Catalog, source_text: str, source_ref: str | None = None
) -> tuple[Workflow, list[str]]:
    unsupported = list(intent.unsupported)
    ref_to_id: dict[str, str] = {}
    trig = intent.trigger
    node = catalog.get(trig.node_type)
    if node and node.kind == "trigger":
        ref_to_id[trig.ref] = str(uuid.uuid4())
    else:
        unsupported.append(f"unsupported trigger: {trig.node_type}")

    kept: list[NodeIntent] = []
    for s in intent.steps:
        node = catalog.get(s.node_type)
        if node is None or node.kind == "trigger":
            # An unknown node with branches was meant as a condition; never invent one.
            what = "condition" if (s.if_true or s.if_false) else "node"
            unsupported.append(f"unsupported {what}: {s.node_type}")
            continue
        ref_to_id[s.ref] = str(uuid.uuid4())
        kept.append(s)

    trigger_id = ref_to_id.get(trig.ref)
    var_map = dict(ref_to_id)
    if trigger_id:
        var_map["trigger"] = trigger_id  # the model may say {{trigger.x}} instead of its own ref

    def build_step(i: NodeIntent, then: str | None = None) -> Step:
        # Simplification: only top-level string params are rewritten; nested values need a recursive walk (upgrade path: walk dicts and lists)
        params = {
            k: rewrite_variables(v, var_map) if isinstance(v, str) else v for k, v in i.params.items()
        }
        return Step(
            id=ref_to_id[i.ref],
            node_type=i.node_type,
            params=params,
            next=ref_to_id.get(then or ""),
            on_true=ref_to_id.get(i.if_true or ""),
            on_false=ref_to_id.get(i.if_false or ""),
        )

    steps = {step.id: step for step in (build_step(s, s.then) for s in kept)}
    trigger = None
    if trigger_id:
        # Unlike other steps, a trigger with no explicit `then` flows into the first step.
        trigger = build_step(trig, trig.then or (kept[0].ref if kept else None))

    as_built = {s.id: copy.deepcopy(s.params) for s in ([trigger] if trigger else []) + list(steps.values())}
    wf = Workflow(
        id=str(uuid.uuid4()),
        name=source_text[:60],
        status="draft",
        trigger=trigger,
        steps=steps,
        built_from=Provenance(
            source_text=source_text,
            source_ref=source_ref,
            as_built_params=as_built,
            as_built_steps={s.id: s.model_copy(deep=True) for s in ([trigger] if trigger else []) + list(steps.values())},
            as_built_trigger_id=trigger.id if trigger else None,
        ),
    )
    return wf, unsupported
