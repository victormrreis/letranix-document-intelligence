"""Reproducible performance measurement on generated synthetic documents.

Measures workspace open time, import and batch processing throughput for text
documents, FTS search latency at that volume, and process peak memory. OCR
timings come from ``python -m letranix benchmark``. Results are written to
docs/evaluation/performance.json. Numbers depend on the machine; the file
records the environment next to them.
"""

import json
import os
import platform
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from letranix.evaluation import generate_split  # noqa: E402
from letranix.service import Letranix  # noqa: E402


def peak_memory_mb() -> float | None:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (n, ctypes.c_size_t) for n in ("PeakWorkingSetSize", "WorkingSetSize",
                                               "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
                                               "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
                                               "PagefileUsage", "PeakPagefileUsage")]
        counters = Counters()
        counters.cb = ctypes.sizeof(Counters)
        ctypes.windll.kernel32.K32GetProcessMemoryInfo(
            ctypes.c_void_p(-1), ctypes.byref(counters), counters.cb)  # -1: current process
        return round(counters.PeakWorkingSetSize / 1e6, 1)
    import resource

    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e3, 1)


def main(n: int = 300):
    tmp = Path(tempfile.mkdtemp(prefix="letranix-perf-"))
    try:
        t0 = time.perf_counter()
        svc = Letranix(tmp, start_workers=False)
        open_ms = (time.perf_counter() - t0) * 1000
        svc.settings.update({"processing.auto_process": False})
        templates = {t["id"]: t for t in svc.templates.all()}
        docs = generate_split(99, n, templates)
        t0 = time.perf_counter()
        ids = [svc.import_bytes(d["name"], d["text"].encode(), "perf")["id"] for d in docs]
        import_s = time.perf_counter() - t0
        svc.queue(ids, "perf")
        t0 = time.perf_counter()
        while svc.run_next_job():
            pass
        process_s = time.perf_counter() - t0
        latencies = []
        for term in ("synthetic", "Supplier", "Grand total", "SO", "zzz-absent", "Inspection"):
            for _ in range(5):
                t0 = time.perf_counter()
                svc.search(q=term, limit=50)
                latencies.append((time.perf_counter() - t0) * 1000)
        t0 = time.perf_counter()
        svc.search(status="needs-review", template="invoice", limit=50)
        filter_ms = (time.perf_counter() - t0) * 1000
        svc.close()
        t0 = time.perf_counter()
        Letranix(tmp, start_workers=False).close()
        reopen_ms = (time.perf_counter() - t0) * 1000
        report = {
            "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "environment": {"python": platform.python_version(), "os": platform.platform(),
                            "cpu_count": os.cpu_count()},
            "documents": n,
            "workspace_create_ms": round(open_ms, 1),
            "workspace_reopen_ms": round(reopen_ms, 1),
            "import_per_document_ms": round(import_s / n * 1000, 2),
            "text_processing_docs_per_second": round(n / process_s, 1),
            "search_median_ms": round(statistics.median(latencies), 2),
            "search_p95_ms": round(sorted(latencies)[int(len(latencies) * 0.95) - 1], 2),
            "filter_query_ms": round(filter_ms, 2),
            "peak_memory_mb": peak_memory_mb(),
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    out = Path("docs/evaluation/performance.json")
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
