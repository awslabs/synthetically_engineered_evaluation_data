import json
import logging
import os

import pandas as pd
from strands import tool

logger = logging.getLogger(__name__)


@tool
def export_data(data_json: str, export_format: str, output_dir: str) -> str:
    """Export generated data to files in the specified format.

    Args:
        data_json: JSON string mapping entity names to lists of records.
        export_format: Output format — one of json, csv, excel, parquet.
        output_dir: Directory to write output files to.

    Returns:
        JSON summary of exported files and record counts.
    """
    logger.info("Exporting data — format: %s, output: %s", export_format, output_dir)

    try:
        data = json.loads(data_json)
    except json.JSONDecodeError:
        # LLM sometimes appends trailing characters — try parsing up to the first valid object
        try:
            decoder = json.JSONDecoder()
            data, _ = decoder.raw_decode(data_json)
            logger.warning("data_json had trailing characters — parsed with raw_decode")
        except (json.JSONDecodeError, ValueError) as e:
            logger.error("Failed to parse data JSON: %s", e)
            return f"Error parsing data JSON: {e}"

    # Unwrap GeneratedSamples format {"data": {entity: [...]}}
    if "data" in data and isinstance(data["data"], dict):
        data = data["data"]

    os.makedirs(output_dir, exist_ok=True)

    files: list[str] = []
    record_counts: dict[str, int] = {}

    # Filter to entity data only (skip metadata keys the LLM may have merged in)
    data = {k: v for k, v in data.items() if isinstance(v, list)}

    # Clear only the files THIS exporter would produce for the current entities,
    # across every known format, so a re-run doesn't leave a stale export (e.g. a
    # prior csv when this run writes parquet). Scoped by name on purpose: the
    # output dir may be shared with the document pipeline or hold unrelated user
    # files, and a blanket wipe of the directory would destroy them.
    _EXPORT_EXTS = ("json", "csv", "xlsx", "parquet")
    for entity_name in data:
        safe_name = entity_name.lower().replace(" ", "_")
        for ext in _EXPORT_EXTS:
            stale = os.path.join(output_dir, f"{safe_name}.{ext}")
            if os.path.isfile(stale):
                os.remove(stale)

    for entity_name, records in data.items():
        if not records:
            logger.warning("Skipping entity '%s' — no records", entity_name)
            continue

        df = pd.DataFrame(records)
        record_counts[entity_name] = len(df)
        safe_name = entity_name.lower().replace(" ", "_")

        if export_format == "json":
            path = os.path.join(output_dir, f"{safe_name}.json")
            df.to_json(path, orient="records", indent=2)
        elif export_format == "csv":
            path = os.path.join(output_dir, f"{safe_name}.csv")
            df.to_csv(path, index=False)
        elif export_format == "excel":
            path = os.path.join(output_dir, f"{safe_name}.xlsx")
            df.to_excel(path, index=False, engine="openpyxl")
        elif export_format == "parquet":
            path = os.path.join(output_dir, f"{safe_name}.parquet")
            df.to_parquet(path, index=False)
        else:
            logger.error("Unsupported export format: %s", export_format)
            return f"Unsupported format: {export_format}"

        logger.info("Exported entity '%s' — %d records → %s", entity_name, len(df), path)
        files.append(path)

    result = {
        "format": export_format,
        "files": files,
        "record_counts": record_counts,
    }
    logger.info("Export complete — %d files written", len(files))
    return json.dumps(result, indent=2)
