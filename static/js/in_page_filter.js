/**
 * Client-side list helpers for tables that live inside a page (e.g. the
 * tabs on the Job Detail page). Complements list_filter.js which drives
 * the URL-based server-side flow on standalone list pages.
 *
 * Usage on a table:
 *
 *   <input data-inpage-filter="#myTable"
 *          data-inpage-count="#myCount"  (optional counter element)
 *          placeholder="Search…">
 *
 *   <table id="myTable">
 *     <thead>
 *       <tr>
 *         <th data-sort-col="0" data-sort-type="text">Date</th>
 *         ...
 *       </tr>
 *     </thead>
 *     <tbody>
 *       <tr>
 *         <td data-value="2025-01-01">2025-01-01</td>
 *         <td data-value="1500" data-total-format="currency">$1,500.00</td>
 *       </tr>
 *     </tbody>
 *     <tfoot>
 *       <tr data-totals-row>
 *         <td colspan="2">Totals</td>
 *         <td data-total-col="2" data-total-format="currency"></td>
 *       </tr>
 *     </tfoot>
 *   </table>
 *
 * Cells with `data-value` are used for numeric sums and for sort. Cells
 * without it fall back to textContent parsed as a number for currency
 * totals, and alphabetical sort.
 */
(function () {
    'use strict';

    function currencyFormat(n) {
        var sign = n < 0 ? '-' : '';
        return sign + '$' + Math.abs(n).toLocaleString('en-US', {
            minimumFractionDigits: 2, maximumFractionDigits: 2,
        });
    }

    function hoursFormat(hours) {
        var h = Math.floor(hours);
        var m = Math.round((hours - h) * 60);
        if (m === 60) { h += 1; m = 0; }
        return h + 'h ' + (m < 10 ? '0' : '') + m + 'm';
    }

    function parseNumber(raw) {
        if (raw === null || raw === undefined) return NaN;
        var cleaned = String(raw).replace(/[$,\s]/g, '').replace(/^-$/, '');
        var n = parseFloat(cleaned);
        return isNaN(n) ? NaN : n;
    }

    function visibleRows(table) {
        var out = [];
        table.querySelectorAll('tbody tr').forEach(function (row) {
            if (row.style.display !== 'none') out.push(row);
        });
        return out;
    }

    function recomputeTotals(table) {
        var tfoot = table.querySelector('tfoot tr[data-totals-row]');
        if (!tfoot) return;
        var totalCells = tfoot.querySelectorAll('td[data-total-col]');
        var rows = visibleRows(table);
        totalCells.forEach(function (cell) {
            var colIndex = parseInt(cell.dataset.totalCol, 10);
            var format = cell.dataset.totalFormat || 'number';
            var total = 0;
            var have = false;
            rows.forEach(function (row) {
                var td = row.cells[colIndex];
                if (!td) return;
                var raw;
                if (td.dataset.value !== undefined) raw = td.dataset.value;
                else if (td.dataset.sortVal !== undefined) raw = td.dataset.sortVal;
                else raw = td.textContent;
                var n = parseNumber(raw);
                if (!isNaN(n)) { total += n; have = true; }
            });
            if (!have) { cell.textContent = ''; return; }
            if (format === 'currency') {
                cell.textContent = currencyFormat(total);
            } else if (format === 'hours') {
                cell.textContent = hoursFormat(total);
            } else if (format === 'percent') {
                // Percent totals are averages — sum ÷ count of rows that had a value.
                var counted = 0;
                rows.forEach(function (r) {
                    var c = r.cells[colIndex];
                    if (!c) return;
                    var raw2 = c.dataset.value !== undefined ? c.dataset.value
                             : (c.dataset.sortVal !== undefined ? c.dataset.sortVal : c.textContent);
                    if (!isNaN(parseNumber(raw2))) counted++;
                });
                cell.textContent = counted ? (total / counted).toFixed(2) + '%' : '';
            } else {
                cell.textContent = total.toLocaleString('en-US');
            }
        });
        var countCell = tfoot.querySelector('[data-total-count]');
        if (countCell) countCell.textContent = rows.length;
    }

    // Expose so pages with their own filter logic (e.g. jobs dashboard)
    // can trigger a totals refresh after hiding/showing rows.
    window.recomputeTableTotals = recomputeTotals;

    function updateCounter(input, visibleCount, totalCount) {
        var sel = input.dataset.inpageCount;
        if (!sel) return;
        var el = document.querySelector(sel);
        if (el) el.textContent = visibleCount + ' of ' + totalCount;
    }

    function wireFilter(input) {
        var table = document.querySelector(input.dataset.inpageFilter);
        if (!table) return;
        var allRows = table.querySelectorAll('tbody tr');
        var total = allRows.length;

        function apply() {
            var q = input.value.toLowerCase().trim();
            var visible = 0;
            allRows.forEach(function (row) {
                var match = !q || row.textContent.toLowerCase().indexOf(q) !== -1;
                row.style.display = match ? '' : 'none';
                if (match) visible++;
            });
            updateCounter(input, visible, total);
            recomputeTotals(table);
        }

        input.addEventListener('input', apply);
        updateCounter(input, total, total);
        recomputeTotals(table);
    }

    function cellSortValue(row, colIndex, sortType) {
        var td = row.cells[colIndex];
        if (!td) return '';
        var raw = td.dataset.value !== undefined ? td.dataset.value : td.textContent.trim();
        if (sortType === 'number' || sortType === 'currency' || sortType === 'hours') {
            var n = parseNumber(raw);
            return isNaN(n) ? -Infinity : n;
        }
        if (sortType === 'date') {
            return raw || '';
        }
        return String(raw).toLowerCase();
    }

    function wireSort(table) {
        var headers = table.querySelectorAll('thead th[data-sort-col]');
        if (!headers.length) return;
        var tbody = table.querySelector('tbody');
        if (!tbody) return;
        var state = { col: -1, asc: true };

        headers.forEach(function (th) {
            th.style.cursor = 'pointer';
            th.classList.add('sortable-th');
            th.addEventListener('click', function () {
                var col = parseInt(th.dataset.sortCol, 10);
                var type = th.dataset.sortType || 'text';
                var asc = (state.col === col) ? !state.asc : true;
                state = { col: col, asc: asc };

                var rows = Array.prototype.slice.call(tbody.querySelectorAll('tr'));
                rows.sort(function (a, b) {
                    var av = cellSortValue(a, col, type);
                    var bv = cellSortValue(b, col, type);
                    if (av < bv) return asc ? -1 : 1;
                    if (av > bv) return asc ? 1 : -1;
                    return 0;
                });
                rows.forEach(function (r) { tbody.appendChild(r); });

                headers.forEach(function (h) { h.classList.remove('sort-asc', 'sort-desc'); });
                th.classList.add(asc ? 'sort-asc' : 'sort-desc');
                recomputeTotals(table);
            });
        });
    }

    document.querySelectorAll('table[data-inpage-sort]').forEach(wireSort);
    document.querySelectorAll('[data-inpage-filter]').forEach(wireFilter);
    // Any table with a tfoot totals row but no filter still gets an
    // initial totals recompute on load.
    document.querySelectorAll('table tfoot tr[data-totals-row]').forEach(function (tr) {
        var table = tr.closest('table');
        if (table) recomputeTotals(table);
    });
})();
