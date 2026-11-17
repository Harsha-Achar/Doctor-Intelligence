import { useQuery } from '@tanstack/react-query';
import { useEffect } from 'react';
import { NavLink, Outlet, useParams } from 'react-router-dom';
import { ErrorState } from '../components/ErrorState';
import { useShell } from '../layouts/shell';
import { fetchOverview } from './api';
import './patients.css';

const TABS = [
  { to: '/patients/analytics', label: 'Journey analytics', end: true },
  { to: '/patients/data', label: 'Data & processing', end: true },
  { to: '/patients/list', label: 'Patients', end: false },
  { to: '/patients/review', label: 'Needs review', end: false },
];

export function PatientsLayout() {
  const shell = useShell();
  const { patientId } = useParams();
  const overview = useQuery({ queryKey: ['pt-overview'], queryFn: ({ signal }) => fetchOverview(signal) });
  useEffect(() => {
    shell.setSubtitle(patientId ? `Patient ${patientId}` : 'One Daiichi patient ID across hub, specialty pharmacy and claims');
    return () => shell.setSubtitle('');
  }, [shell, patientId]);
  const reviewCount = overview.data?.needs_review;
  const brands = overview.data?.brands || [
    { brand: 'Brand A', description: 'HER2 infusion' },
    { brand: 'Brand B', description: 'TROP2 infusion' },
    { brand: 'Brand C', description: 'Oral AML tablet' },
  ];
  return (
    <div className="patients">
      <div className="pthead">
        <div className="seg" role="tablist">
          {TABS.map((tab) => (
            <NavLink key={tab.to} to={tab.to} end={tab.end} className={({ isActive }) => (isActive ? 'on' : '')}>
              {tab.label}
              {tab.to.endsWith('/review') && reviewCount ? ` (${reviewCount})` : ''}
            </NavLink>
          ))}
        </div>
      </div>
      <div className="brandkey">
        {brands.map((item) => (
          <span key={item.brand}>
            <b>{item.brand}</b> {item.description}
          </span>
        ))}
      </div>
      {overview.isError ? <ErrorState message="Patient analytics could not be loaded." onRetry={() => overview.refetch()} /> : null}
      <Outlet />
    </div>
  );
}
