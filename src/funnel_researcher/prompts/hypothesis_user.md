I need you to diagnose a developer-funnel dropoff for an API product. All the artifacts you need are below.

## The funnel definition

```yaml
{funnel_yaml}
```

Target step under investigation: **{target_dropoff_step}**

## The dropoff data

```json
{dropoff_json}
```

## The product artifacts

**Each file below is shown with line numbers prefixed to every line in the format `{{N:4d}}  {{line}}`.** When you cite `file:line` evidence in your hypotheses, use these prefixed line numbers exactly. Do not estimate or count lines yourself — read the prefix.

The artifacts are organized by category. They are the developer's surface area: what they see, what they import, what they get back when something goes wrong.

### README.md

```markdown
{readme_content}
```

### docs/

{docs_section}

### sdk/

{sdk_section}

### errors / error catalog

{errors_section}

{additional_files_section}

## What I need

Produce a funnel-diagnosis report following the structure described in your system prompt. Two to three structurally distinct hypotheses, each with file:line evidence AND a dropoff signal, each with a structured edit spec.

The four-layer categorization should reflect where the cause of dropoff at `{target_dropoff_step}` actually lives. Walk through your eight self-checks before emitting.
