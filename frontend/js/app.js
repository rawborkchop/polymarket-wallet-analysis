/**
 * Polymarket Analytics - Vue.js 3 Application
 */

const { createApp, ref, reactive, computed, watch, onMounted, nextTick } = Vue;

createApp({
    setup() {
        // State
        const sidebarOpen = ref(true);
        const currentView = ref('dashboard');
        const isLoading = ref(false);
        const currentTime = ref('');

        const navItems = [
            { id: 'dashboard', label: 'Dashboard', icon: 'fas fa-chart-pie' },
            { id: 'wallets', label: 'Wallets', icon: 'fas fa-wallet' },
            { id: 'trades', label: 'Trades', icon: 'fas fa-exchange-alt' },
        ];

        // Dashboard data
        const dashboardData = reactive({ total_wallets: 0, total_trades: 0, total_volume: 0, total_analyses: 0, top_wallets: [], recent_analyses: [] });

        // Data
        const wallets = ref([]);
        const trades = ref([]);
        const selectedWallet = ref(null);
        const walletStats = ref(null);
        const walletTrades = ref([]);
        const walletTradeFilter = ref('all');

        // Trade view
        const selectedTradeWallet = ref('');
        const tradeFilterSide = ref('');
        const tradeSearch = ref('');
        const tradePage = ref(1);
        const tradePageSize = 25;

        // Wallet management
        const showAddWalletModal = ref(false);
        const newWalletAddress = ref('');
        const newWalletName = ref('');
        const isAddingWallet = ref(false);
        const addWalletError = ref('');

        // Timeline/range extension
        const isExtendingRange = ref(false);
        const extendDays = ref(30);

        // Chart date range filtering
        const chartStartDate = ref(null);
        const chartEndDate = ref(null);

        const showDeleteModal = ref(false);
        const walletToDelete = ref(null);

        // Charts
        const dashboardVolumeChart = ref(null);
        const pnlChart = ref(null);
        const volumeChart = ref(null);
        const buySellChart = ref(null);
        const marketPnlChart = ref(null);

        let chartInstances = {};

        // Toasts
        const toasts = ref([]);

        // Computed
        const currentViewTitle = computed(() => navItems.find(n => n.id === currentView.value)?.label || 'Dashboard');

        const dashboardStats = computed(() => [
            { label: 'Wallets Tracked', value: dashboardData.total_wallets, icon: 'fas fa-wallet', bgColor: 'bg-blue-900/30', iconColor: 'text-blue-400' },
            { label: 'Total Trades', value: formatNumber(dashboardData.total_trades), icon: 'fas fa-exchange-alt', bgColor: 'bg-green-900/30', iconColor: 'text-green-400' },
            { label: 'Total Volume', value: formatCurrency(dashboardData.total_volume), icon: 'fas fa-dollar-sign', bgColor: 'bg-purple-900/30', iconColor: 'text-purple-400' },
            { label: 'Analyses', value: dashboardData.total_analyses, icon: 'fas fa-chart-line', bgColor: 'bg-orange-900/30', iconColor: 'text-orange-400' },
        ]);

        const topWallets = computed(() => dashboardData.top_wallets || []);

        const filteredWalletTrades = computed(() => {
            if (walletTradeFilter.value === 'all') return walletTrades.value;
            return walletTrades.value.filter(t => t.side === walletTradeFilter.value);
        });

        const filteredTrades = computed(() => {
            let result = [...trades.value];
            if (selectedTradeWallet.value) {
                const w = wallets.value.find(w => w.id === parseInt(selectedTradeWallet.value));
                if (w) result = result.filter(t => t.wallet_address === w.address);
            }
            if (tradeFilterSide.value) result = result.filter(t => t.side === tradeFilterSide.value);
            if (tradeSearch.value) {
                const s = tradeSearch.value.toLowerCase();
                result = result.filter(t => t.market_title?.toLowerCase().includes(s));
            }
            return result;
        });

        const totalTradePages = computed(() => Math.ceil(filteredTrades.value.length / tradePageSize) || 1);
        const paginatedTrades = computed(() => filteredTrades.value.slice((tradePage.value - 1) * tradePageSize, tradePage.value * tradePageSize));

        // Methods
        function updateTime() {
            currentTime.value = new Date().toLocaleString('en-US', { weekday: 'short', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
        }

        async function refreshData() {
            isLoading.value = true;
            try {
                await Promise.all([fetchDashboard(), fetchWallets(), fetchTrades()]);
                showToast('Data refreshed', 'success');
            } catch (e) {
                showToast('Refresh failed', 'error');
            } finally {
                isLoading.value = false;
            }
        }

        async function fetchDashboard() {
            try {
                const data = await api.getDashboard();
                Object.assign(dashboardData, data);
                await nextTick();
                initDashboardChart();
            } catch (e) { console.error(e); }
        }

        async function fetchWallets() {
            try {
                const data = await api.getWallets();
                wallets.value = data.results || data;
            } catch (e) { console.error(e); }
        }

        async function fetchTrades() {
            try {
                const data = await api.getTrades({ limit: 500 });
                trades.value = data.results || data;
            } catch (e) { console.error(e); }
        }

        async function selectWallet(wallet, forceRefresh = false) {
            if (!forceRefresh && selectedWallet.value?.id === wallet.id) return;
            selectedWallet.value = wallet;
            walletStats.value = null;
            walletTrades.value = [];

            // Reset chart date range to show all data
            chartStartDate.value = null;
            chartEndDate.value = null;

            try {
                const [stats, tradesData] = await Promise.all([
                    api.getWalletStats(wallet.id, chartStartDate.value, chartEndDate.value),
                    api.getWalletTrades(wallet.id),
                ]);
                walletStats.value = stats;
                walletTrades.value = tradesData || [];
                await nextTick();
                initWalletCharts();
            } catch (e) {
                showToast('Failed to load wallet', 'error');
            }
        }

        async function filterChartsByDateRange(startDate, endDate) {
            if (!selectedWallet.value) return;
            chartStartDate.value = startDate;
            chartEndDate.value = endDate;
            try {
                const stats = await api.getWalletStats(selectedWallet.value.id, startDate, endDate);
                walletStats.value = stats;
                await nextTick();
                initWalletCharts();
                showToast(`Showing ${startDate || 'start'} to ${endDate || 'end'}`, 'info');
            } catch (e) {
                showToast('Failed to filter charts', 'error');
            }
        }

        function showLastNDays(days) {
            const end = new Date();
            const start = new Date();
            start.setDate(start.getDate() - days);
            filterChartsByDateRange(
                start.toISOString().split('T')[0],
                end.toISOString().split('T')[0]
            );
        }

        function showAllData() {
            filterChartsByDateRange(null, null);
        }

        function goToWallet(wallet) {
            currentView.value = 'wallets';
            selectWallet(wallet);
        }

        // Wallet Management
        async function addWallet() {
            if (!newWalletAddress.value || isAddingWallet.value) return;
            isAddingWallet.value = true;
            addWalletError.value = '';
            try {
                const result = await api.addWallet(newWalletAddress.value, newWalletName.value);
                showToast(result.message || 'Wallet added', 'success');
                showAddWalletModal.value = false;
                newWalletAddress.value = '';
                newWalletName.value = '';
                await fetchWallets();
            } catch (e) {
                addWalletError.value = e.message || 'Failed to add wallet';
            } finally {
                isAddingWallet.value = false;
            }
        }

        async function refreshWalletData(wallet) {
            showToast('Refreshing wallet data...', 'info');
            try {
                await api.refreshWallet(wallet.id);
                showToast('Refresh started in background', 'success');
                setTimeout(() => fetchWallets(), 3000);
            } catch (e) {
                showToast('Refresh failed', 'error');
            }
        }

        async function extendRange(wallet, direction) {
            if (isExtendingRange.value) return;
            isExtendingRange.value = true;
            showToast(`Extending range ${direction}...`, 'info');
            try {
                const result = await api.extendWalletRange(wallet.id, {
                    direction,
                    days: extendDays.value
                });
                showToast(`Fetching data from ${result.start_date} to ${result.end_date}`, 'success');

                // Poll for completion and auto-refresh
                const pollInterval = setInterval(async () => {
                    try {
                        await fetchWallets();
                        const updatedWallet = wallets.value.find(w => w.id === wallet.id);
                        if (updatedWallet) {
                            // Check if date range has expanded
                            const oldStart = wallet.data_start_date;
                            const newStart = updatedWallet.data_start_date;
                            if (oldStart !== newStart || !isExtendingRange.value) {
                                clearInterval(pollInterval);
                                isExtendingRange.value = false;
                                showToast('Data range extended!', 'success');
                                if (selectedWallet.value?.id === wallet.id) {
                                    await selectWallet(updatedWallet, true);
                                }
                            }
                        }
                    } catch (e) {
                        console.error('Poll error:', e);
                    }
                }, 3000);

                // Safety timeout after 60 seconds
                setTimeout(() => {
                    clearInterval(pollInterval);
                    isExtendingRange.value = false;
                }, 60000);

            } catch (e) {
                showToast('Failed to extend range', 'error');
                isExtendingRange.value = false;
            }
        }

        function getTimelineData(wallet) {
            if (!wallet) return null;
            const startDate = wallet.data_start_date ? new Date(wallet.data_start_date) : null;
            const endDate = wallet.data_end_date ? new Date(wallet.data_end_date) : null;
            if (!startDate || !endDate) return null;

            const today = new Date();
            const daysDiff = Math.ceil((endDate - startDate) / (1000 * 60 * 60 * 24));
            const daysToToday = Math.ceil((today - endDate) / (1000 * 60 * 60 * 24));

            return {
                startDate: formatDate(startDate),
                endDate: formatDate(endDate),
                daysCovered: daysDiff,
                daysToToday: daysToToday,
                isUpToDate: daysToToday <= 1
            };
        }

        function confirmDeleteWallet(wallet) {
            walletToDelete.value = wallet;
            showDeleteModal.value = true;
        }

        async function deleteWallet() {
            if (!walletToDelete.value) return;
            try {
                await api.deleteWallet(walletToDelete.value.id);
                showToast('Wallet deleted', 'success');
                if (selectedWallet.value?.id === walletToDelete.value.id) {
                    selectedWallet.value = null;
                    walletStats.value = null;
                }
                showDeleteModal.value = false;
                walletToDelete.value = null;
                await fetchWallets();
            } catch (e) {
                showToast('Delete failed', 'error');
            }
        }

        // Charts
        function initDashboardChart() {
            if (!dashboardVolumeChart.value) return;
            const ctx = dashboardVolumeChart.value.getContext('2d');
            if (chartInstances.dashboard) chartInstances.dashboard.destroy();

            const volumeByDate = {};
            trades.value.forEach(t => {
                const date = t.datetime?.split('T')[0];
                if (date) volumeByDate[date] = (volumeByDate[date] || 0) + parseFloat(t.total_value || 0);
            });

            const dates = Object.keys(volumeByDate).sort().slice(-14);
            chartInstances.dashboard = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: dates.map(d => formatDate(d)),
                    datasets: [{ data: dates.map(d => volumeByDate[d]), backgroundColor: 'rgba(14,165,233,0.6)', borderRadius: 4 }]
                },
                options: chartOptions()
            });
        }

        function initWalletCharts() {
            if (!walletStats.value) return;
            const stats = walletStats.value;

            // Real P&L Chart
            if (pnlChart.value && stats.daily_pnl?.length) {
                if (chartInstances.pnl) chartInstances.pnl.destroy();
                const data = [...stats.daily_pnl].reverse();
                const finalPnl = data[data.length - 1]?.cumulative_pnl || 0;
                const isPositive = finalPnl >= 0;
                chartInstances.pnl = new Chart(pnlChart.value.getContext('2d'), {
                    type: 'line',
                    data: {
                        labels: data.map(d => formatDate(d.date)),
                        datasets: [{
                            data: data.map(d => d.cumulative_pnl),
                            borderColor: isPositive ? '#22c55e' : '#ef4444',
                            backgroundColor: isPositive ? 'rgba(34,197,94,0.1)' : 'rgba(239,68,68,0.1)',
                            fill: true, tension: 0.4
                        }]
                    },
                    options: chartOptions('$')
                });
            }

            // Volume Chart
            if (volumeChart.value && stats.daily_pnl?.length) {
                if (chartInstances.volume) chartInstances.volume.destroy();
                const data = [...stats.daily_pnl].reverse();
                chartInstances.volume = new Chart(volumeChart.value.getContext('2d'), {
                    type: 'bar',
                    data: {
                        labels: data.map(d => formatDate(d.date)),
                        datasets: [{ data: data.map(d => d.volume), backgroundColor: 'rgba(14,165,233,0.6)', borderRadius: 4 }]
                    },
                    options: chartOptions('$')
                });
            }

            // Activity Distribution Chart (Buys, Sells, Redeems, Merges, Splits)
            if (buySellChart.value) {
                if (chartInstances.buySell) chartInstances.buySell.destroy();
                const activities = stats.activity_by_type || {};
                const redeems = activities.REDEEM?.count || 0;
                const merges = activities.MERGE?.count || 0;
                const splits = activities.SPLIT?.count || 0;

                chartInstances.buySell = new Chart(buySellChart.value.getContext('2d'), {
                    type: 'doughnut',
                    data: {
                        labels: ['Buys', 'Sells', 'Redeems', 'Merges', 'Splits'].filter((_, i) =>
                            [stats.total_buys, stats.total_sells, redeems, merges, splits][i] > 0),
                        datasets: [{
                            data: [stats.total_buys, stats.total_sells, redeems, merges, splits].filter(v => v > 0),
                            backgroundColor: ['#22c55e', '#ef4444', '#8b5cf6', '#f97316', '#06b6d4'],
                            borderWidth: 0
                        }]
                    },
                    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom', labels: { color: '#9ca3af', font: { size: 10 } } } } }
                });
            }

            // Market PNL Chart
            if (marketPnlChart.value && stats.pnl_by_market?.length) {
                if (chartInstances.marketPnl) chartInstances.marketPnl.destroy();
                const markets = stats.pnl_by_market.slice(0, 5);
                chartInstances.marketPnl = new Chart(marketPnlChart.value.getContext('2d'), {
                    type: 'bar',
                    data: {
                        labels: markets.map(m => (m.market__title || 'Unknown').slice(0, 20) + '...'),
                        datasets: [{
                            data: markets.map(m => m.estimated_pnl),
                            backgroundColor: markets.map(m => m.estimated_pnl >= 0 ? 'rgba(34,197,94,0.6)' : 'rgba(239,68,68,0.6)'),
                            borderRadius: 4
                        }]
                    },
                    options: { ...chartOptions('$'), indexAxis: 'y' }
                });
            }
        }

        function chartOptions(prefix = '') {
            return {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { grid: { color: 'rgba(75,85,99,0.3)' }, ticks: { color: '#9ca3af' } },
                    y: { grid: { color: 'rgba(75,85,99,0.3)' }, ticks: { color: '#9ca3af', callback: v => prefix + formatNumber(v) } }
                }
            };
        }

        function exportTrades() {
            const csv = ['Time,Wallet,Market,Side,Size,Price,Value,TxHash',
                ...filteredTrades.value.map(t => `${t.datetime},"${t.wallet_address}","${(t.market_title||'').replace(/"/g,'""')}",${t.side},${t.size},${t.price},${t.total_value},${t.transaction_hash}`)
            ].join('\n');
            const a = document.createElement('a');
            a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
            a.download = `trades_${new Date().toISOString().split('T')[0]}.csv`;
            a.click();
            showToast('Exported', 'success');
        }

        function showToast(message, type = 'info') {
            const id = Date.now();
            toasts.value.push({ id, message, type });
            setTimeout(() => toasts.value = toasts.value.filter(t => t.id !== id), 4000);
        }

        // Formatters
        function formatNumber(n) { return n == null ? '0' : new Intl.NumberFormat('en-US').format(Math.round(n)); }
        function formatCurrency(n) {
            if (n == null) return '$0';
            const v = parseFloat(n);
            if (isNaN(v)) return '$0';
            if (Math.abs(v) >= 1e6) return '$' + (v/1e6).toFixed(2) + 'M';
            if (Math.abs(v) >= 1e3) return '$' + (v/1e3).toFixed(2) + 'K';
            return '$' + v.toFixed(2);
        }
        function formatAddress(a) { return a ? a.slice(0,6) + '...' + a.slice(-4) : ''; }
        function formatDateTime(d) { return d ? new Date(d).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : ''; }
        function formatDate(d) { return d ? new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : ''; }

        // Watchers
        watch([selectedTradeWallet, tradeFilterSide, tradeSearch], () => tradePage.value = 1);
        watch(currentView, async (v) => {
            if (v === 'wallets' && !wallets.value.length) await fetchWallets();
            else if (v === 'trades' && !trades.value.length) await fetchTrades();
        });

        // Lifecycle
        onMounted(() => {
            updateTime();
            setInterval(updateTime, 1000);
            refreshData();
            setInterval(fetchDashboard, 30000);
        });

        return {
            sidebarOpen, currentView, currentViewTitle, isLoading, currentTime, navItems,
            dashboardStats, topWallets,
            wallets, selectedWallet, walletStats, walletTrades, walletTradeFilter, filteredWalletTrades,
            trades, filteredTrades, paginatedTrades, selectedTradeWallet, tradeFilterSide, tradeSearch, tradePage, totalTradePages,
            showAddWalletModal, newWalletAddress, newWalletName, isAddingWallet, addWalletError,
            showDeleteModal, walletToDelete,
            isExtendingRange, extendDays, chartStartDate, chartEndDate,
            dashboardVolumeChart, pnlChart, volumeChart, buySellChart, marketPnlChart,
            toasts,
            refreshData, selectWallet, goToWallet, addWallet, refreshWalletData, extendRange, getTimelineData,
            filterChartsByDateRange, showLastNDays, showAllData,
            confirmDeleteWallet, deleteWallet, exportTrades,
            formatNumber, formatCurrency, formatAddress, formatDateTime, formatDate,
        };
    },
}).mount('#app');
