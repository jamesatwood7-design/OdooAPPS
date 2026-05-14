"""Chunked XLSX writer.

`ChunkedXlsx('invoices', 5000)` writes rows into invoices_001.xlsx,
invoices_002.xlsx, ... rolling to a new file whenever chunk_size is reached.
Every file shares the same header row.
"""
import os

from openpyxl import Workbook


class ChunkedXlsx:
    def __init__(self, out_dir, basename, columns, chunk_size=5000,
                 prefix=''):
        """
        out_dir:    directory the .xlsx files land in.
        basename:   e.g. 'invoices' -> 'invoices_001.xlsx' etc.
        columns:    ordered list of column headers.
        chunk_size: rows per file (header excluded).
        prefix:     optional numeric ordering prefix like '06_' applied to
                    the on-disk filename, kept out of basename for clarity.
        """
        if chunk_size < 1:
            raise ValueError('chunk_size must be >= 1')
        os.makedirs(out_dir, exist_ok=True)
        self.out_dir = out_dir
        self.basename = basename
        self.prefix = prefix
        self.columns = list(columns)
        self.chunk_size = chunk_size
        self._chunk_no = 0
        self._rows_in_chunk = 0
        self._wb = None
        self._ws = None
        self._paths = []
        self._total = 0

    def _open_new_chunk(self):
        self._flush_chunk()
        self._chunk_no += 1
        self._wb = Workbook(write_only=True)
        self._ws = self._wb.create_sheet(self.basename[:31] or 'Sheet1')
        self._ws.append(self.columns)
        self._rows_in_chunk = 0

    def _current_path(self):
        return os.path.join(
            self.out_dir,
            f'{self.prefix}{self.basename}_{self._chunk_no:03d}.xlsx',
        )

    def _flush_chunk(self):
        if self._wb is None:
            return
        path = self._current_path()
        self._wb.save(path)
        self._paths.append(path)
        self._wb = None
        self._ws = None

    def write_row(self, row_dict):
        """row_dict keyed by column name; missing keys land as empty cells."""
        if self._wb is None or self._rows_in_chunk >= self.chunk_size:
            self._open_new_chunk()
        cells = [row_dict.get(c, '') for c in self.columns]
        # openpyxl write-only mode does not accept None for some cell types;
        # coerce None -> ''.
        cells = ['' if c is None else c for c in cells]
        self._ws.append(cells)
        self._rows_in_chunk += 1
        self._total += 1

    def close(self):
        self._flush_chunk()

    @property
    def total_rows(self):
        return self._total

    @property
    def paths(self):
        return list(self._paths)
