document.addEventListener('DOMContentLoaded', function () {
    var table = document.getElementById('jobsTable');
    if (!table) return;

    var headers = table.querySelectorAll('th.sortable');
    var tbody = table.querySelector('tbody');
    var searchInput = document.getElementById('jobSearch');
    var jobCountEl = document.getElementById('jobCount');
    var currentSort = { col: -1, asc: true };

    // Sorting
    headers.forEach(function (th) {
        th.style.cursor = 'pointer';
        th.addEventListener('click', function () {
            var colIndex = parseInt(th.dataset.colIndex);
            var sortType = th.dataset.sortType;
            var asc = (currentSort.col === colIndex) ? !currentSort.asc : true;

            sortTable(colIndex, sortType, asc);

            // Update sort indicators
            headers.forEach(function (h) {
                h.classList.remove('sort-asc', 'sort-desc');
            });
            th.classList.add(asc ? 'sort-asc' : 'sort-desc');
            currentSort = { col: colIndex, asc: asc };
        });
    });

    function sortTable(colIndex, sortType, asc) {
        var rows = Array.from(tbody.querySelectorAll('tr'));

        rows.sort(function (a, b) {
            var aVal = getCellSortValue(a, colIndex, sortType);
            var bVal = getCellSortValue(b, colIndex, sortType);

            if (aVal < bVal) return asc ? -1 : 1;
            if (aVal > bVal) return asc ? 1 : -1;
            return 0;
        });

        rows.forEach(function (row) {
            tbody.appendChild(row);
        });
    }

    function getCellSortValue(row, colIndex, sortType) {
        var cell = row.cells[colIndex];
        if (!cell) return '';
        var val = cell.dataset.sortVal || cell.textContent.trim();

        if (sortType === 'number' || sortType === 'currency' || sortType === 'percent') {
            var num = parseFloat(String(val).replace(/[$,%,\s]/g, ''));
            return isNaN(num) ? -Infinity : num;
        }
        if (sortType === 'date') {
            if (!val || val === 'False' || val === 'false') return '';
            return val;
        }
        return String(val).toLowerCase();
    }

    // Search / filter
    if (searchInput) {
        searchInput.addEventListener('input', function () {
            var query = this.value.toLowerCase().trim();
            var rows = tbody.querySelectorAll('tr');
            var visible = 0;

            rows.forEach(function (row) {
                var text = row.textContent.toLowerCase();
                var match = !query || text.indexOf(query) !== -1;
                row.style.display = match ? '' : 'none';
                if (match) visible++;
            });

            if (jobCountEl) {
                jobCountEl.textContent = visible;
            }
        });
    }
});
