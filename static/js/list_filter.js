(function () {
    'use strict';

    function wire(input) {
        var tableSel = input.dataset.listFilter;
        var counterSel = input.dataset.listCounter;
        var chipsSel = input.dataset.listChips;

        var table = tableSel ? document.querySelector(tableSel) : null;
        if (!table) return;

        var counter = counterSel ? document.querySelector(counterSel) : null;
        var rows = Array.prototype.slice.call(table.querySelectorAll('tbody tr'));
        var currentStatus = 'all';

        function apply() {
            var q = input.value.toLowerCase().trim();
            var n = 0;
            for (var i = 0; i < rows.length; i++) {
                var row = rows[i];
                var statusOk = currentStatus === 'all' ||
                    (row.dataset.status || '') === currentStatus;
                var textOk = !q || row.textContent.toLowerCase().indexOf(q) !== -1;
                var visible = statusOk && textOk;
                row.style.display = visible ? '' : 'none';
                if (visible) n++;
            }
            if (counter) counter.textContent = n;
        }

        input.addEventListener('input', apply);

        if (chipsSel) {
            var chips = document.querySelectorAll(chipsSel + ' .filter-chip');
            chips.forEach(function (chip) {
                chip.addEventListener('click', function () {
                    currentStatus = this.dataset.status || 'all';
                    chips.forEach(function (c) { c.classList.remove('active'); });
                    this.classList.add('active');
                    apply();
                });
            });
        }
    }

    document.querySelectorAll('[data-list-filter]').forEach(wire);
})();
