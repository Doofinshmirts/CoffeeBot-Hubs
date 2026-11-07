-- Fictional demo hubs at illustrative coordinates. Not operating collection sites.
insert into public.hubs(name,address,latitude,longitude,instructions) values
('Demo Hub A · Campus Corner','Illustrative campus location, Bras Basah',1.2963,103.8502,'Demo only. Tare the empty container, weigh the grounds, and record a photograph. Collection is supervised by the team.'),
('Demo Hub B · Garden Loop','Illustrative garden location, Fort Canning',1.2950,103.8460,'Demo only. Bring a reusable container. Ask the team before collecting and have staff mark the entire batch collected.'),
('Demo Hub C · Community Table','Illustrative community location, Bencoolen',1.3002,103.8520,'Demo only. Check available batches and the recorded time. No real drop-off or collection is offered at this location.')
on conflict(name) do nothing;
