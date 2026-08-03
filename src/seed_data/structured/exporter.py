import json
import logging
import os

import pandas as pd
from strands import tool

logger = logging.getLogger(__name__)

# Extensions this exporter owns, per format. Used both to pick the output path and
# to clear the previous run's files for the same entity.
_FORMAT_EXTS = {"json": "json", "csv": "csv", "excel": "xlsx", "parquet": "parquet"}


def _parquet_engine_error() -> str | None:
    """Return an actionable message if no parquet engine is installed, else None.

    ``DataFrame.to_parquet`` needs pyarrow or fastparquet. pyarrow ships in the
    ``[structured]`` extra, but a user can end up without one (a hand-pinned
    environment, or an older install predating that pin), and pandas' own error
    ("Unable to find a usable engine") names neither the package to install nor
    this project's extra. Checked *before* any file is touched so an unusable
    format fails fast instead of after a full generation run.
    """
    from importlib.util import find_spec

    if find_spec("pyarrow") or find_spec("fastparquet"):
        return None
    return (
        "Parquet export needs a parquet engine, which is not installed. "
        "Install the structured extra (`pip install 'seed-data[structured]'`) "
        "or a single engine (`pip install pyarrow`). "
        "Alternatively export with --format csv."
    )


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

    files: list[str] = []
    record_counts: dict[str, int] = {}

    # Filter to entity data only (skip metadata keys the LLM may have merged in)
    data = {k: v for k, v in data.items() if isinstance(v, list)}

    # Validate everything that can be known up front, BEFORE deleting anything or
    # writing a byte. The cleanup below is destructive and is not rolled back, so
    # bailing out after it would leave the user with neither the new export nor the
    # previous one — a failed run used to empty the directory it was writing into.
    if export_format not in _FORMAT_EXTS:
        logger.error("Unsupported export format: %s", export_format)
        return f"Unsupported format: {export_format}. Use one of: {', '.join(sorted(_FORMAT_EXTS))}"

    if export_format == "parquet":
        engine_error = _parquet_engine_error()
        if engine_error:
            logger.error("%s", engine_error)
            return f"Error: {engine_error}"

    os.makedirs(output_dir, exist_ok=True)

    # Clear only the files THIS exporter would produce for the current entities,
    # across every known format, so a re-run doesn't leave a stale export (e.g. a
    # prior csv when this run writes parquet). Scoped by name on purpose: the
    # output dir may be shared with the document pipeline or hold unrelated user
    # files, and a blanket wipe of the directory would destroy them.
    for entity_name in data:
        safe_name = entity_name.lower().replace(" ", "_")
        for ext in _FORMAT_EXTS.values():
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
        # Format was validated above, so this lookup cannot KeyError.
        path = os.path.join(output_dir, f"{safe_name}.{_FORMAT_EXTS[export_format]}")

        if export_format == "json":
            df.to_json(path, orient="records", indent=2)
        elif export_format == "csv":
            df.to_csv(path, index=False)
        elif export_format == "excel":
            df.to_excel(path, index=False, engine="openpyxl")
        else:  # parquet — engine presence checked before any file was touched
            df.to_parquet(path, index=False)

        logger.info("Exported entity '%s' — %d records → %s", entity_name, len(df), path)
        files.append(path)

    result = {
        "format": export_format,
        "files": files,
        "record_counts": record_counts,
    }
    logger.info("Export complete — %d files written", len(files))
    return json.dumps(result, indent=2)
