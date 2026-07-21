# use-cases-spec-trim

Trim use-cases spec to requirements-only; relocate invented SHALL NOT negative-space language, implementation-narrative paragraphs, the int/TaskId facade-boundary prose, and the stale AbandonNode discard(task_id) recipe into GRACE markup on yascheduler/application/{submit_task,allocate_task,consume_task,deallocate_nodes,abandon_node,query_tasks,allocation_tracker}.py. Replace the one stale AbandonNode scenario with accurate discard_by_node-based scenarios; add the missing AllocateTask empty-platforms short-circuit scenario.
