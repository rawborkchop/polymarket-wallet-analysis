/**
 * API Service for Polymarket Analytics
 * Handles all communication with the Django backend
 */

const API_BASE = 'http://127.0.0.1:8000/api';

class ApiService {
    constructor(baseUrl = API_BASE) {
        this.baseUrl = baseUrl;
    }

    async request(endpoint, options = {}) {
        const url = `${this.baseUrl}${endpoint}`;
        const config = {
            headers: {
                'Content-Type': 'application/json',
                ...options.headers,
            },
            ...options,
        };

        try {
            const response = await fetch(url, config);

            if (!response.ok) {
                const error = await response.json().catch(() => ({}));
                throw new Error(error.detail || error.error || `HTTP ${response.status}`);
            }

            return await response.json();
        } catch (error) {
            console.error(`API Error [${endpoint}]:`, error);
            throw error;
        }
    }

    // Dashboard
    async getDashboard() {
        return this.request('/dashboard/');
    }

    // Wallets
    async getWallets(params = {}) {
        const query = new URLSearchParams(params).toString();
        return this.request(`/wallets/${query ? '?' + query : ''}`);
    }

    async getWallet(id) {
        return this.request(`/wallets/${id}/`);
    }

    async getWalletStats(id, chartStart = null, chartEnd = null) {
        let url = `/wallets/${id}/stats/`;
        const params = new URLSearchParams();
        if (chartStart) params.append('chart_start', chartStart);
        if (chartEnd) params.append('chart_end', chartEnd);
        if (params.toString()) url += '?' + params.toString();
        return this.request(url);
    }

    async getWalletTrades(walletId, params = {}) {
        const query = new URLSearchParams(params).toString();
        return this.request(`/wallets/${walletId}/trades/${query ? '?' + query : ''}`);
    }

    // Wallet Management
    async addWallet(address, name = '') {
        return this.request('/wallets/add/', {
            method: 'POST',
            body: JSON.stringify({ address, name }),
        });
    }

    async refreshWallet(id) {
        return this.request(`/wallets/${id}/refresh/`, {
            method: 'POST',
        });
    }

    async deleteWallet(id) {
        return this.request(`/wallets/${id}/delete/`, {
            method: 'DELETE',
        });
    }

    async extendWalletRange(id, options) {
        // options: { direction: 'backward'|'forward', days: 30 }
        // or: { start_date: '2024-01-01', end_date: '2024-01-31' }
        return this.request(`/wallets/${id}/extend-range/`, {
            method: 'POST',
            body: JSON.stringify(options),
        });
    }

    // Trades
    async getTrades(params = {}) {
        const query = new URLSearchParams(params).toString();
        return this.request(`/trades/${query ? '?' + query : ''}`);
    }

    async getTrade(id) {
        return this.request(`/trades/${id}/`);
    }

    // Markets
    async getMarkets(params = {}) {
        const query = new URLSearchParams(params).toString();
        return this.request(`/markets/${query ? '?' + query : ''}`);
    }

    // Analyses
    async getAnalyses(params = {}) {
        const query = new URLSearchParams(params).toString();
        return this.request(`/analyses/${query ? '?' + query : ''}`);
    }

    async getAnalysis(id) {
        return this.request(`/analyses/${id}/`);
    }
}

// Export singleton instance
const api = new ApiService();
