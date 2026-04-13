/**
 * Cascading dropdown: load tasks when a project is selected.
 */
function onProjectChange(projectId) {
    var taskSelect = document.getElementById('task_id');
    var accountSelect = document.getElementById('account_id');

    // Clear current tasks
    if (taskSelect) {
        taskSelect.innerHTML = '<option value="">-- Select Task --</option>';
    }

    if (!projectId) return;

    // Fetch tasks for the selected project
    if (taskSelect) {
        fetch('/jobcosting/api/tasks/' + projectId)
            .then(function (resp) { return resp.json(); })
            .then(function (tasks) {
                if (Array.isArray(tasks)) {
                    tasks.forEach(function (task) {
                        var option = document.createElement('option');
                        option.value = task.id;
                        option.textContent = task.name;
                        taskSelect.appendChild(option);
                    });
                }
            })
            .catch(function (err) {
                console.error('Error loading tasks:', err);
            });
    }

    // Auto-select the project's analytic account
    if (accountSelect) {
        fetch('/jobcosting/api/project-account/' + projectId)
            .then(function (resp) { return resp.json(); })
            .then(function (data) {
                if (data.account_id) {
                    accountSelect.value = data.account_id;
                }
            })
            .catch(function (err) {
                console.error('Error loading project account:', err);
            });
    }
}

/**
 * Calculate estimated cost as hours * rate.
 */
document.addEventListener('DOMContentLoaded', function () {
    var hoursInput = document.getElementById('hours');
    var rateInput = document.getElementById('hourly_rate');
    var costDisplay = document.getElementById('estimatedCost');

    function updateCost() {
        if (!hoursInput || !rateInput || !costDisplay) return;
        var hours = parseFloat(hoursInput.value) || 0;
        var rate = parseFloat(rateInput.value) || 0;
        var cost = hours * rate;
        costDisplay.textContent = '$' + cost.toFixed(2);
    }

    if (hoursInput) hoursInput.addEventListener('input', updateCost);
    if (rateInput) rateInput.addEventListener('input', updateCost);

    // Check if project_id is pre-selected via URL params
    var projectSelect = document.getElementById('project_id');
    if (projectSelect && projectSelect.value) {
        onProjectChange(projectSelect.value);
    }
});
